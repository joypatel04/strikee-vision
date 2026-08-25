"""Snapshot store: saves a labelled evidence image when a game starts.

Images go to a local, date-organised folder (works fully offline). Each image is
stamped with the asset name and timestamp so staff reconciliation is
self-explanatory. Optional best-effort S3 upload and a weekly cleanup are
provided; local storage is the reliable default.

Upload is S3-compatible, which includes Cloudflare R2 - but only if the endpoint
is supplied. Without one, boto3 talks to AWS, so an R2 bucket name would upload
into someone else's namespace or fail outright. The endpoint and region fall
back to the STRIKEE_BACKUP_* values so one set of credentials covers both this
and the database backup.

Layout:  <base>/<venue_id>/<YYYY-MM-DD>/<asset>_<HHMMSS>.jpg
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]


class SnapshotStore:
    def __init__(self, base_dir: str = "snapshots", s3_bucket: Optional[str] = None,
                 s3_endpoint: Optional[str] = None, s3_region: Optional[str] = None,
                 quality: Optional[int] = None):
        self.base = Path(base_dir)
        # OpenCV defaults to JPEG quality 95, which roughly doubles the file for
        # no visible gain on an evidence image someone glances at. 80 is the
        # difference between ~160KB and ~75KB per snapshot, and there are three
        # per game (session start, game start, game end).
        self.quality = int(quality if quality is not None
                           else os.environ.get("STRIKEE_SNAPSHOT_QUALITY", "80"))
        self.s3_bucket = s3_bucket or os.environ.get("STRIKEE_S3_BUCKET")
        # Fall back to the backup settings: pointing both at the same R2 account
        # is the normal case, and two copies of one endpoint is two chances to
        # get it wrong.
        self.s3_endpoint = (s3_endpoint or os.environ.get("STRIKEE_S3_ENDPOINT")
                            or os.environ.get("STRIKEE_BACKUP_ENDPOINT"))
        self.s3_region = (s3_region or os.environ.get("STRIKEE_S3_REGION")
                          or os.environ.get("STRIKEE_BACKUP_REGION") or "auto")
        # Upload is best-effort, so failures must be visible somewhere or they
        # are invisible everywhere.
        self.uploads_ok = 0
        self.uploads_failed = 0
        self.last_upload_error: Optional[str] = None

    def save(self, venue_id: str, asset_id: str, asset_name: str, frame,
             ts: Optional[str] = None) -> Optional[str]:
        """Write a labelled JPEG and return its path relative to base (or None
        if the frame is missing). `frame` is a BGR numpy array."""
        if frame is None:
            return None
        import cv2  # lazy

        now = datetime.now(timezone.utc).astimezone()
        date_dir = now.strftime("%Y-%m-%d")
        stamp = now.strftime("%H%M%S")
        rel = os.path.join(_safe(venue_id), date_dir, f"{_safe(asset_name)}_{stamp}.jpg")
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)

        labelled = frame.copy()
        caption = f"{asset_name}  {now.strftime('%Y-%m-%d %H:%M:%S')}"
        cv2.rectangle(labelled, (0, 0), (labelled.shape[1], 34), (0, 0, 0), -1)
        cv2.putText(labelled, caption, (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 255, 255), 2)
        cv2.imwrite(str(path), labelled, [cv2.IMWRITE_JPEG_QUALITY, self.quality])

        self._maybe_upload(path, rel)
        return rel

    def _client(self):
        import boto3  # lazy, optional dependency
        kwargs = {"region_name": self.s3_region}
        if self.s3_endpoint:
            kwargs["endpoint_url"] = self.s3_endpoint
        return boto3.client("s3", **kwargs)

    def _maybe_upload(self, path: Path, key: str) -> None:
        if not self.s3_bucket:
            return
        try:  # best-effort; never block the pipeline
            self._client().upload_file(str(path), self.s3_bucket, key)
            self.uploads_ok += 1
        except Exception as exc:
            self.uploads_failed += 1
            self.last_upload_error = f"{type(exc).__name__}: {exc}"[:200]

    def upload_status(self) -> dict:
        """Whether snapshot upload is configured and working, for diagnostics."""
        return {
            "enabled": bool(self.s3_bucket),
            "bucket": self.s3_bucket,
            "endpoint": self.s3_endpoint or "AWS S3 (no endpoint set)",
            "region": self.s3_region,
            "uploaded": self.uploads_ok,
            "failed": self.uploads_failed,
            "last_error": self.last_upload_error,
        }

    def disk_usage(self) -> dict:
        """How much local disk the snapshots are taking. Unbounded growth is the
        failure mode here - a venue box quietly fills its own disk."""
        count = 0
        total = 0
        if self.base.exists():
            for f in self.base.rglob("*.jpg"):
                try:
                    total += f.stat().st_size
                    count += 1
                except OSError:
                    pass
        return {"files": count, "megabytes": round(total / 1e6, 1)}

    def cleanup(self, keep_days: int = 7) -> int:
        """Delete snapshot images older than keep_days. Returns count removed.

        Local images are the working copy; anything uploaded stays in the bucket,
        so this trims disk without losing the archive.
        """
        if not self.base.exists():
            return 0
        cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=keep_days)
        removed = 0
        for f in self.base.rglob("*.jpg"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime).astimezone()
                if mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        return removed
