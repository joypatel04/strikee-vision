"""SQLite → object-storage backup. Keeps the single local SQLite DB as the
source of truth and ships a consistent snapshot to S3-compatible storage
(Cloudflare R2 recommended — free tier, no egress fees) for durability.

A snapshot is taken with `VACUUM INTO`, which produces a transactionally
consistent, defragmented copy even while the pipeline is writing (we run WAL
mode) — so you never upload a torn file. Upload is best-effort: it never blocks
or crashes the pipeline, and does nothing when storage isn't configured.

Configure via env (all optional — absent = backups disabled):
  STRIKEE_BACKUP_BUCKET     bucket / R2 bucket name
  STRIKEE_BACKUP_ENDPOINT   S3 endpoint (R2: https://<accountid>.r2.cloudflarestorage.com)
  STRIKEE_BACKUP_PREFIX     key prefix (default "strikee")
  STRIKEE_BACKUP_REGION     region (default "auto" — correct for R2)
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY   credentials (R2 token key/secret)
  STRIKEE_BACKUP_EVERY_MIN  if set, the app backs up on this interval automatically
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class BackupConfig:
    bucket: Optional[str] = None
    endpoint: Optional[str] = None
    prefix: str = "strikee"
    region: str = "auto"

    @property
    def enabled(self) -> bool:
        return bool(self.bucket)

    @classmethod
    def from_env(cls) -> "BackupConfig":
        return cls(
            bucket=os.environ.get("STRIKEE_BACKUP_BUCKET"),
            endpoint=os.environ.get("STRIKEE_BACKUP_ENDPOINT"),
            prefix=os.environ.get("STRIKEE_BACKUP_PREFIX", "strikee"),
            region=os.environ.get("STRIKEE_BACKUP_REGION", "auto"),
        )


def snapshot_db(db_path: str, dest_path: str) -> str:
    """Write a consistent copy of the live SQLite DB to dest_path via
    VACUUM INTO. dest_path must not already exist."""
    con = sqlite3.connect(db_path)
    try:
        # VACUUM INTO wants a string literal; dest_path is ours (a temp file),
        # so escape single quotes defensively and inline it.
        safe = dest_path.replace("'", "''")
        con.execute(f"VACUUM INTO '{safe}'")
    finally:
        con.close()
    return dest_path


def _client(cfg: BackupConfig):
    import boto3  # lazy, optional dependency
    kwargs = {"region_name": cfg.region}
    if cfg.endpoint:
        kwargs["endpoint_url"] = cfg.endpoint
    return boto3.client("s3", **kwargs)


def run_once(db_path: str, cfg: Optional[BackupConfig] = None,
             clock=None) -> Optional[str]:
    """Snapshot the DB and upload it under a timestamped key plus a stable
    'latest' key. Returns the timestamped key on success, else None. Best-effort
    — swallows all errors so a backup failure never affects the venue."""
    cfg = cfg or BackupConfig.from_env()
    if not cfg.enabled:
        return None
    if not os.path.exists(db_path):
        return None
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    tmp = os.path.join(tempfile.gettempdir(), f"strikee-backup-{stamp}.db")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        snapshot_db(db_path, tmp)
        key = f"{cfg.prefix}/strikee-{stamp}.db"
        client = _client(cfg)
        client.upload_file(tmp, cfg.bucket, key)
        client.upload_file(tmp, cfg.bucket, f"{cfg.prefix}/strikee-latest.db")
        return key
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def main() -> None:
    """One-shot CLI: `strikee-backup`. Point a scheduled task at it (Windows
    Task Scheduler / cron) to back up every few minutes, or set
    STRIKEE_BACKUP_EVERY_MIN to let the app do it automatically."""
    import argparse
    ap = argparse.ArgumentParser(description="Back up the SQLite DB to S3/R2")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    args = ap.parse_args()
    cfg = BackupConfig.from_env()
    if not cfg.enabled:
        print("backup disabled — set STRIKEE_BACKUP_BUCKET (+ endpoint/creds)")
        raise SystemExit(1)
    key = run_once(args.db, cfg)
    if key:
        print(f"backed up -> {cfg.bucket}/{key}  (+ {cfg.prefix}/strikee-latest.db)")
    else:
        print("backup FAILED — check bucket/endpoint/credentials/network")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
