"""State Engine — the heart of the pipeline.

Per Asset, it combines the asset's sensors' raw observations into three
independent facets (presence / activity / health), applies primary/supporting
fusion and hysteresis smoothing, and derives a single display label.

Design decisions realized here (see docs/specification-pack/17 G02, G03):
  - State is three facets, each with confidence; health takes display priority.
  - Multiple cameras on one asset = primary + supporting sensors -> one state.
    Presence override: occupied if primary is occupied OR any supporting is
    occupied with high confidence (occlusion causes false empties).
  - Smoothing: presence flips to present after `enter_ticks` consecutive
    present reads and to absent after `exit_ticks` consecutive absent reads.
  - Activity detection is not implemented in M2 (open decision D-T4); the
    activity facet stays 'unknown', so a present asset shows 'Occupied'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .types import (
    AssetRuntime, AssetSnapshot, RawObservation,
    PRESENCE_ABSENT, PRESENCE_PRESENT, PRESENCE_UNKNOWN,
    ACTIVITY_ACTIVE, ACTIVITY_INACTIVE, ACTIVITY_UNKNOWN,
    HEALTH_OK, HEALTH_DEGRADED, HEALTH_OFFLINE,
    ROLE_PRIMARY, ROLE_SUPPORTING,
)

_NO_OBS = RawObservation(False, 0.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class _AssetState:
    presence: str = PRESENCE_UNKNOWN
    activity: str = ACTIVITY_UNKNOWN
    health: str = HEALTH_OFFLINE
    label: str = "Unknown"
    confidence: float = 0.0
    effective_at: str = ""
    present_streak: int = 0
    absent_streak: int = 0
    activity_still: int = 0


class StateEngine:
    def __init__(self, enter_ticks: int = 2, exit_ticks: int = 3,
                 support_high_conf: float = 0.6, activity_still_ticks: int = 3,
                 clock=_now, enter_sec: float | None = None,
                 exit_sec: float | None = None, still_sec: float | None = None,
                 interval_for=None):
        self.enter_ticks = enter_ticks
        self.exit_ticks = exit_ticks
        self.support_high_conf = support_high_conf
        self.activity_still_ticks = activity_still_ticks
        self._clock = clock
        # Grace windows in SECONDS, converted per asset. Optional: leave unset
        # and the fixed tick counts above are used exactly as before.
        self.enter_sec = enter_sec
        self.exit_sec = exit_sec
        self.still_sec = still_sec
        self.interval_for = interval_for   # callable(asset) -> seconds | None
        self._states: dict[str, _AssetState] = {}

    def snapshot(self, asset: AssetRuntime) -> AssetSnapshot:
        st = self._states.setdefault(asset.id, _AssetState())
        return AssetSnapshot(
            asset_id=asset.id, name=asset.name,
            business_unit_id=asset.business_unit_id,
            presence=st.presence, activity=st.activity, health=st.health,
            label=st.label, confidence=st.confidence,
            effective_at=st.effective_at or self._clock(),
        )

    def update(
        self,
        asset: AssetRuntime,
        raw_by_sensor: dict[str, RawObservation],
        source_ok: dict[str, bool],
    ) -> tuple[AssetSnapshot, bool]:
        """Feed one tick of observations for an asset. Returns (snapshot, changed)."""
        st = self._states.setdefault(asset.id, _AssetState())
        prev_label = st.label
        enter_ticks, exit_ticks, still_ticks = self._thresholds(asset)

        occ_sensors = [s for s in asset.sensors
                       if s.kind in ("occupancy", "presence", "snooker_game")]
        # A screen sensor GATES the asset: a gaming station is in use only when
        # somebody is there AND the TV is on. Somebody sitting on the sofa with
        # the screen off is not playing, and billing them would be exactly the
        # leakage this system exists to measure. The gate runs before smoothing,
        # so the usual exit window still applies - a dark loading screen or a
        # missed read cannot end a session on its own.
        screen_sensors = [s for s in asset.sensors if s.kind == "screen"]

        # --- health facet: from the sources backing this asset's sensors ---
        st.health = self._derive_health(occ_sensors or screen_sensors, source_ok)

        # --- presence facet: primary/supporting fusion + smoothing ---
        if st.health == HEALTH_OFFLINE or not occ_sensors:
            # no usable evidence this tick -> don't advance streaks, go unknown
            st.presence = PRESENCE_UNKNOWN
            st.present_streak = st.absent_streak = 0
            st.confidence = 0.0
        else:
            raw_present, conf = self._fuse_presence(occ_sensors, raw_by_sensor, source_ok)
            if screen_sensors and raw_present:
                screen_on = any(
                    raw_by_sensor.get(s.id, _NO_OBS).present
                    for s in screen_sensors
                    if source_ok.get(s.source_id, False))
                if not screen_on:
                    raw_present = False
            self._smooth_presence(st, raw_present, enter_ticks, exit_ticks)
            st.confidence = conf

        # --- activity facet: movement-based (D-T4) ---
        if st.presence == PRESENCE_PRESENT:
            raw_active = any(
                raw_by_sensor.get(s.id, _NO_OBS).active
                for s in occ_sensors if source_ok.get(s.source_id, False)
            )
            self._smooth_activity(st, raw_active, still_ticks)
        else:
            st.activity = ACTIVITY_UNKNOWN
            st.activity_still = 0

        st.label = self._derive_label(st)
        changed = st.label != prev_label
        if changed or not st.effective_at:
            st.effective_at = self._clock()
        return self.snapshot(asset), changed

    # -- internals ---------------------------------------------------------

    def _thresholds(self, asset: AssetRuntime) -> tuple[int, int, int]:
        """Streak lengths for this asset, as (enter, exit, still).

        A tick count is not a duration. Tables are grabbed every ~13s and
        gaming stations every ~5s, so exit_ticks=3 frees a table after 39s but
        a station after 15s - the same setting meaning very different things,
        which is exactly how one evening of play fragments into several
        sessions. When a window is given in seconds we convert it using the
        asset's own sampling interval, so "free it after two minutes" means
        two minutes everywhere.
        """
        enter, leave, still = (self.enter_ticks, self.exit_ticks,
                               self.activity_still_ticks)
        interval = None
        if self.interval_for is not None:
            try:
                interval = self.interval_for(asset)
            except Exception:
                interval = None      # never let tuning break state derivation
        if interval and interval > 0:
            if self.enter_sec:
                enter = max(1, round(self.enter_sec / interval))
            if self.exit_sec:
                leave = max(1, round(self.exit_sec / interval))
            if self.still_sec:
                still = max(1, round(self.still_sec / interval))
        return enter, leave, still

    def _derive_health(self, occ_sensors, source_ok) -> str:
        source_ids = {s.source_id for s in occ_sensors if s.source_id}
        if not source_ids:
            return HEALTH_OFFLINE
        oks = [bool(source_ok.get(sid, False)) for sid in source_ids]
        if all(oks):
            return HEALTH_OK
        if any(oks):
            return HEALTH_DEGRADED
        return HEALTH_OFFLINE

    def _fuse_presence(self, occ_sensors, raw_by_sensor, source_ok) -> tuple[bool, float]:
        primaries = [s for s in occ_sensors if s.role == ROLE_PRIMARY]
        supporting = [s for s in occ_sensors if s.role == ROLE_SUPPORTING]
        # If no explicit primary, treat all as primary-equivalent (any present).
        if not primaries:
            primaries = occ_sensors
            supporting = []

        def obs(s):
            return raw_by_sensor.get(s.id, RawObservation(False, 0.0))

        # Primary decides, but only from healthy sources.
        prim_present = False
        prim_conf = 0.0
        for s in primaries:
            if source_ok.get(s.source_id, False):
                o = obs(s)
                if o.present:
                    prim_present = True
                    prim_conf = max(prim_conf, o.confidence)

        # Presence override: a confident supporting 'occupied' beats an empty
        # primary (occlusion causes false empties, rarely false occupied).
        sup_present = False
        sup_conf = 0.0
        for s in supporting:
            if source_ok.get(s.source_id, False):
                o = obs(s)
                if o.present and o.confidence >= self.support_high_conf:
                    sup_present = True
                    sup_conf = max(sup_conf, o.confidence)

        present = prim_present or sup_present
        conf = max(prim_conf, sup_conf) if present else max(
            [obs(s).confidence for s in primaries], default=0.0
        )
        return present, conf

    def _smooth_presence(self, st: _AssetState, raw_present: bool,
                         enter_ticks: int, exit_ticks: int) -> None:
        if raw_present:
            st.present_streak += 1
            st.absent_streak = 0
        else:
            st.absent_streak += 1
            st.present_streak = 0

        if st.presence != PRESENCE_PRESENT and st.present_streak >= enter_ticks:
            st.presence = PRESENCE_PRESENT
        elif st.presence != PRESENCE_ABSENT and st.absent_streak >= exit_ticks:
            st.presence = PRESENCE_ABSENT
        elif st.presence == PRESENCE_UNKNOWN:
            # before either threshold is met, remain unknown
            pass

    def _smooth_activity(self, st: _AssetState, raw_active: bool,
                         still_ticks: int) -> None:
        """Movement -> active immediately; stillness -> inactive only after
        activity_still_ticks consecutive still reads (avoids flicker between
        shots). Before that threshold, activity stays as-is (unknown right
        after arrival, so the asset reads 'Occupied' not a false 'Active')."""
        if raw_active:
            st.activity = ACTIVITY_ACTIVE
            st.activity_still = 0
        else:
            st.activity_still += 1
            if st.activity_still >= still_ticks:
                st.activity = ACTIVITY_INACTIVE

    def _derive_label(self, st: _AssetState) -> str:
        # health takes display priority — a broken camera never shows a
        # confident business status.
        if st.health == HEALTH_OFFLINE:
            return "Unknown"
        if st.health == HEALTH_DEGRADED:
            return "Degraded"
        if st.presence == PRESENCE_ABSENT:
            return "Available"
        if st.presence == PRESENCE_PRESENT:
            if st.activity == ACTIVITY_ACTIVE:
                return "Active (In Use)"
            if st.activity == ACTIVITY_INACTIVE:
                return "Occupied – Idle"
            return "Occupied"
        return "Unknown"
