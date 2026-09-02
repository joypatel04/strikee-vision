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


def _shift(iso: str, seconds: float) -> str:
    """`iso` moved back by `seconds`. Returns it unchanged if unparseable, so a
    clock injected by a test can never break state derivation."""
    if not seconds:
        return iso
    try:
        from datetime import timedelta
        return (datetime.fromisoformat(iso)
                - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return iso


_NEVER_ON = 1 << 30   # 'has not been on within any hold window'


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
    presence_since: str = ""     # when presence ACTUALLY changed, best estimate
    # Consecutive reads with every screen dark. Starts 'cold' - a screen not
    # yet seen on has no hold to spend, so a sofa in front of a dead TV is
    # never billed for the grace window.
    screen_off_streak: int = _NEVER_ON


class StateEngine:
    def __init__(self, enter_ticks: int = 2, exit_ticks: int = 3,
                 support_high_conf: float = 0.6, activity_still_ticks: int = 3,
                 clock=_now, enter_sec: float | None = None,
                 exit_sec: float | None = None, still_sec: float | None = None,
                 interval_for=None, screen_hold_ticks: int = 2):
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
        # How many consecutive dark reads a screen gets before it closes the
        # gate. See _screen_allows for why this is not zero.
        self.screen_hold_ticks = screen_hold_ticks
        self._states: dict[str, _AssetState] = {}

    def snapshot(self, asset: AssetRuntime) -> AssetSnapshot:
        st = self._states.setdefault(asset.id, _AssetState())
        return AssetSnapshot(
            asset_id=asset.id, name=asset.name,
            business_unit_id=asset.business_unit_id,
            presence=st.presence, activity=st.activity, health=st.health,
            label=st.label, confidence=st.confidence,
            effective_at=st.effective_at or self._clock(),
            presence_since=st.presence_since or None,
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
            interval = None
            if self.interval_for is not None:
                try:
                    interval = self.interval_for(asset)
                except Exception:
                    interval = None
            raw_present, conf = self._fuse_presence(occ_sensors, raw_by_sensor, source_ok)
            if screen_sensors:
                raw_present = self._screen_allows(st, screen_sensors, raw_by_sensor,
                                                  source_ok, raw_present)
            self._smooth_presence(st, raw_present, enter_ticks, exit_ticks, interval)
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

    def _screen_allows(self, st: _AssetState, screen_sensors, raw_by_sensor,
                       source_ok, raw_present: bool) -> bool:
        """The TV gate, with a short hold on the last 'on' reading.

        A station counts as occupied only while its screen is on, which is what
        separates someone playing from someone resting on the sofa. But 'on' is
        read from one still frame - bright enough, or different enough from the
        last frame - and a television that is genuinely on fails both tests
        several times an hour: a dark level, a loading screen, a fade between
        cutscenes.

        Closing the gate on the first dark read does more damage than it looks.
        It does not merely mark the station free for one read; because presence
        needs `enter_ticks` CONSECUTIVE present reads, a screen flickering
        around the threshold resets the streak every time and the station never
        opens at all - even with the player detected in every single frame.

        So a dark read is only believed once it repeats. The streak advances on
        every tick, occupied or not, so an empty station with its TV off cannot
        bank grace for the next person to arrive.
        """
        screen_on = any(
            raw_by_sensor.get(s.id, _NO_OBS).present
            for s in screen_sensors
            if source_ok.get(s.source_id, False))
        if screen_on:
            st.screen_off_streak = 0
        else:
            st.screen_off_streak += 1
        if raw_present and st.screen_off_streak > self.screen_hold_ticks:
            return False
        return raw_present

    def _smooth_presence(self, st: _AssetState, raw_present: bool,
                         enter_ticks: int, exit_ticks: int,
                         interval: float | None = None) -> None:
        """Smooth the raw reads, and record when presence *really* changed.

        The flip happens only once the whole window has elapsed, so stamping a
        session with the flip time runs both ends late - and by different
        amounts, since entering takes a couple of reads and leaving takes the
        full grace window. The net effect is every session recorded roughly the
        exit window longer than it was, which on a venue billing by time is not
        a rounding error.

        The reads themselves say when it changed: presence began at the FIRST
        present read of the streak, and ended at the LAST present read before
        the absent streak. Both are a known number of intervals ago.
        """
        if raw_present:
            st.present_streak += 1
            st.absent_streak = 0
        else:
            st.absent_streak += 1
            st.present_streak = 0

        now = self._clock()
        if st.presence != PRESENCE_PRESENT and st.present_streak >= enter_ticks:
            st.presence = PRESENCE_PRESENT
            # they arrived at the first read of this streak
            st.presence_since = _shift(now, (enter_ticks - 1) * (interval or 0))
        elif st.presence != PRESENCE_ABSENT and st.absent_streak >= exit_ticks:
            st.presence = PRESENCE_ABSENT
            # they left just after the last present read, exit_ticks reads ago
            st.presence_since = _shift(now, exit_ticks * (interval or 0))
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
