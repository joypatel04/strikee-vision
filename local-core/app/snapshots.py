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
        # Region: "auto" is an R2 convention and is NOT a valid AWS region -
        # boto3 would try to reach s3.auto.amazonaws.com and fail. So only
        # default to it when an endpoint says we are talking to something
        # R2-shaped; for real S3, leave it unset and let boto3 resolve the
        # region the normal way (AWS_DEFAULT_REGION, or the shared config).
        explicit = (s3_region or os.environ.get("STRIKEE_S3_REGION")
                    or os.environ.get("STRIKEE_BACKUP_REGION"))
        self.s3_region = explicit or ("auto" if self.s3_endpoint else None)
        # What reaches the cloud. Evidence images are the ones worth paying to
        # keep - three per game, tied to a session someone may query months
        # later. "none" keeps the local archive and the bucket untouched, for a
        # venue that wants the images but not the bill.
        self.upload_policy = (os.environ.get("STRIKEE_S3_UPLOAD", "all")
                              or "all").strip().lower()
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

        kwargs = {}
        if self.s3_region:
            kwargs["region_name"] = self.s3_region
        if self.s3_endpoint:
            kwargs["endpoint_url"] = self.s3_endpoint
        try:
            from botocore.config import Config
            # boto3 defaults to 60s connect and read timeouts. Upload happens
            # inline while the processing lock is held, so a stalled network
            # would freeze the whole pipeline for a minute per image. Bound it:
            # an evidence upload is never worth blocking tracking for.
            kwargs["config"] = Config(
                connect_timeout=5, read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            )
        except Exception:
            pass
        return boto3.client("s3", **kwargs)

    def _maybe_upload(self, path: Path, key: str) -> None:
        if not self.s3_bucket or self.upload_policy == "none":
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
            "enabled": bool(self.s3_bucket) and self.upload_policy != "none",
            "policy": self.upload_policy,
            "bucket": self.s3_bucket,
            "endpoint": self.s3_endpoint or "AWS S3 (no endpoint set)",
            "region": self.s3_region or "resolved by boto3 (AWS_DEFAULT_REGION)",
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

    def _archive_files(self):
        """Every evidence image, newest last. Excludes the live-frame directory:
        those are a fixed-size working set that rewrites itself, not archive, and
        deleting them because the pipeline was off for a month would throw away
        the most useful thing to look at when you come back to a stopped system.
        """
        live = self.base / LiveFrameStore.DIRNAME
        files = []
        for f in self.base.rglob("*.jpg"):
            try:
                if live in f.parents:
                    continue
                files.append((f.stat().st_mtime, f))
            except OSError:
                pass
        files.sort()
        return files

    def cleanup(self, keep_days: int = 7, max_mb: float = 0) -> int:
        """Trim the local evidence archive. Returns the number of images removed.

        Two bounds, because age alone is not one. keep_days answers "how far back
        do we care", but says nothing about how much disk that takes - a busy
        weekend can write more in two days than a quiet fortnight, and the box
        this runs on has one small disk shared with the database. max_mb is the
        bound that actually protects the disk; age is the one that matches how
        people think about evidence.

        Anything uploaded stays in the bucket, so this only trims the local
        working copy.
        """
        if not self.base.exists():
            return 0
        files = self._archive_files()
        removed = 0

        if keep_days > 0:
            cutoff = (datetime.now(timezone.utc).astimezone()
                      - timedelta(days=keep_days)).timestamp()
            kept = []
            for mtime, f in files:
                if mtime < cutoff:
                    try:
                        f.unlink()
                        removed += 1
                        continue
                    except OSError:
                        pass
                kept.append((mtime, f))
            files = kept

        if max_mb and max_mb > 0:
            budget = max_mb * 1024 * 1024
            total = 0
            sizes = []
            for mtime, f in files:
                try:
                    sizes.append((mtime, f, f.stat().st_size))
                    total += sizes[-1][2]
                except OSError:
                    pass
            # Oldest first until back under budget.
            for _, f, size in sizes:
                if total <= budget:
                    break
                try:
                    f.unlink()
                    total -= size
                    removed += 1
                except OSError:
                    pass
        return removed


class LiveFrameStore:
    """The most recent frame from each camera, for looking at - not for keeping.

    Three properties matter, and they are the opposite of SnapshotStore's:

    * ONE file per camera, overwritten in place. Ten cameras is ten files,
      today and in a year. There is nothing to prune because nothing
      accumulates - which is the only bound worth having on something written
      every few seconds.
    * NEVER uploaded. An evidence image is written three times a game and is
      worth cloud storage; a live frame is written all day and is worthless ten
      seconds later. Uploading these would be paying to store noise, so this
      class has no S3 client at all - not a disabled one, none.
    * Written outside the date tree, so the evidence archive stays a clean
      record of games and is not diluted by thousands of look-at-me frames.

    Layout:  <base>/live/<venue_id>/<source_id>.jpg
    """

    DIRNAME = "live"

    def __init__(self, base_dir: str = "snapshots", quality: int = 70,
                 max_width: int = 960):
        self.base = Path(base_dir) / self.DIRNAME
        self.quality = int(quality)
        self.max_width = int(max_width)
        self.written = 0
        self.last_error: Optional[str] = None

    def _path(self, venue_id: str, source_id: str) -> Path:
        return self.base / _safe(venue_id) / f"{_safe(source_id)}.jpg"

    def write(self, venue_id: str, source_id: str, frame) -> Optional[str]:
        """Overwrite this camera's live frame. Best-effort: a failure here must
        never interrupt tracking, which is the actual job."""
        if frame is None:
            return None
        import cv2  # lazy

        path = self._path(venue_id, source_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write via a temp file in the same directory and replace: the HTTP
            # handler may be reading this exact path while we write it, and a
            # half-written JPEG renders as a grey box in the dashboard.
            # The temp name must keep the .jpg suffix: OpenCV chooses its
            # encoder from the extension, so writing to a ".tmp" fails outright
            # with "could not find a writer" - and best-effort error handling
            # would turn that into no live frames and no explanation.
            tmp = path.with_name(path.name + ".part.jpg")
            cv2.imwrite(str(tmp), frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            os.replace(tmp, path)
            self.written += 1
            return str(path)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return None

    def path_for(self, venue_id: str, source_id: str) -> Optional[Path]:
        path = self._path(venue_id, source_id)
        return path if path.exists() else None

    def describe(self, venue_id: str, source_id: str) -> dict:
        """Age and size, so the dashboard can say 'this is 4 seconds old' rather
        than showing a stale picture as if it were current."""
        path = self._path(venue_id, source_id)
        if not path.exists():
            return {"available": False, "age_sec": None, "bytes": None}
        stat = path.stat()
        age = (datetime.now(timezone.utc)
               - datetime.fromtimestamp(stat.st_mtime, timezone.utc)).total_seconds()
        return {"available": True, "age_sec": round(max(0.0, age), 1),
                "bytes": stat.st_size}
