"""Analytics: aggregates over Sessions, Events, and Metric Samples.

Everything here is traceable to those three sources — never raw video (D014).
Business Unit is a first-class analytics dimension.
"""
from __future__ import annotations

from typing import Optional


class AnalyticsStore:
    def __init__(self, db):
        self.db = db

    def summary_by_business_unit(self, venue_id: str) -> list[dict]:
        """Per Business Unit: session count, total + average duration, and how
        many sessions are still open. Voided sessions are excluded."""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(business_unit_id, 'unattributed') AS business_unit_id,
                          COUNT(*) AS session_count,
                          COALESCE(SUM(duration_sec), 0) AS total_duration_sec,
                          COALESCE(AVG(duration_sec), 0) AS avg_duration_sec,
                          SUM(CASE WHEN end_ts IS NULL THEN 1 ELSE 0 END) AS open_sessions
                   FROM sessions
                   WHERE venue_id = ? AND status != 'voided'
                   GROUP BY business_unit_id
                   ORDER BY session_count DESC""",
                (venue_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["avg_duration_sec"] = round(r["avg_duration_sec"], 1)
        return rows

    def asset_utilization(self, venue_id: str) -> list[dict]:
        """Per asset: number of sessions and total occupied seconds (from
        session durations). Open sessions contribute their count only."""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT asset_id,
                          COUNT(*) AS session_count,
                          COALESCE(SUM(duration_sec), 0) AS occupied_sec
                   FROM sessions
                   WHERE venue_id = ? AND status != 'voided'
                   GROUP BY asset_id
                   ORDER BY occupied_sec DESC""",
                (venue_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def event_counts(self, venue_id: str) -> list[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT type, COUNT(*) AS count FROM events
                   WHERE venue_id = ? GROUP BY type ORDER BY count DESC""",
                (venue_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def occupancy_series(self, venue_id: str, asset_id: str,
                         metric: str = "present") -> list[dict]:
        """Average of a scalar metric bucketed by hour (from metric samples).
        This is the source for average/peak/by-hour metrics that events and
        sessions cannot produce."""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT substr(ts, 1, 13) AS hour,
                          AVG(value) AS avg_value,
                          MAX(value) AS peak_value,
                          COUNT(*)   AS samples
                   FROM metric_samples
                   WHERE venue_id = ? AND asset_id = ? AND metric = ?
                   GROUP BY hour ORDER BY hour""",
                (venue_id, asset_id, metric),
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["avg_value"] = round(r["avg_value"], 3)
        return rows

    def venue_overview(self, venue_id: str) -> dict:
        """Headline numbers for the dashboard 'today' strip."""
        with self.db.cursor() as cur:
            cur.execute(
                """SELECT
                     (SELECT COUNT(*) FROM sessions WHERE venue_id = ? AND end_ts IS NULL
                        AND status != 'voided') AS active_sessions,
                     (SELECT COUNT(*) FROM sessions WHERE venue_id = ? AND status != 'voided')
                        AS total_sessions,
                     (SELECT COUNT(*) FROM events WHERE venue_id = ?) AS total_events""",
                (venue_id, venue_id, venue_id),
            )
            return dict(cur.fetchone())
