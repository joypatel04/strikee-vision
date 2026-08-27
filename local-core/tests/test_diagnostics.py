"""Diagnostics: does the panel tell the truth about what is in effect?

The question it answers is a Windows one - `set VAR=x` applies only to the
window it was typed in, so a setting can look configured and simply never
reach the process. Reporting the *source* of every value is the point.
"""
import os

import pytest

from app.diagnostics import config_report, model_report, warnings


@pytest.fixture
def clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("STRIKEE_", "TURSO_")):
            monkeypatch.delenv(key, raising=False)


def _by_name(cfg):
    return {c["name"]: c for c in cfg}


def test_unset_knob_reports_its_default_not_the_environment(clean_env):
    cfg = _by_name(config_report())
    k = cfg["STRIKEE_MAX_STREAMS"]
    assert k["source"] == "default"
    assert k["effective"] == 3


def test_set_knob_reports_as_environment(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_EXIT_SEC", "120")
    k = _by_name(config_report())["STRIKEE_EXIT_SEC"]
    assert k["source"] == "environment"
    assert k["effective"] == 120.0


def test_optional_knob_with_no_default_reads_unset(clean_env):
    assert _by_name(config_report())["STRIKEE_EXIT_SEC"]["source"] == "unset"


def test_unparseable_value_is_reported_not_raised(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_RATE_TABLE", "abc")
    k = _by_name(config_report())["STRIKEE_RATE_TABLE"]
    assert k["error"] and k["effective"] is None


def test_secrets_are_masked(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.super.secret.value")
    k = _by_name(config_report())["TURSO_AUTH_TOKEN"]
    assert "secret" not in k["value"]
    assert k["value"].startswith("set (")


# ------------------------------------------------------------------ warnings


def _warn_texts(cfg=None, perception=None, models=None):
    perception = perception or {"torch": "2.0.1", "opencv": "4.9", "numpy": "1.26",
                                "ultralytics": "8.3", "libsql": None, "ready": True}
    models = models if models is not None else [
        {"role": "snooker", "path": "best.pt", "exists": True, "size_mb": 6.0},
        {"role": "person", "path": "yolo11n.pt", "exists": True, "size_mb": 5.6}]
    return [w["text"] for w in warnings(cfg or config_report(), perception, models)]


def test_too_many_streams_is_an_error(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_MAX_STREAMS", "6")
    assert any("STRIKEE_MAX_STREAMS=6" in t for t in _warn_texts())


def test_three_streams_is_fine(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_MAX_STREAMS", "3")
    assert not any("MAX_STREAMS" in t for t in _warn_texts())


def test_seconds_and_ticks_together_warns_which_wins(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_EXIT_SEC", "120")
    monkeypatch.setenv("STRIKEE_EXIT_TICKS", "3")
    assert any("STRIKEE_EXIT_SEC wins" in t for t in _warn_texts())


def test_missing_model_is_an_error(clean_env):
    models = [{"role": "snooker", "path": "best.pt", "exists": False, "size_mb": None}]
    assert any("snooker model missing" in t for t in _warn_texts(models=models))


def test_turso_without_token_is_an_error(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    assert any("TURSO_AUTH_TOKEN is not" in t for t in _warn_texts())


def test_turso_without_libsql_is_an_error(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")
    assert any("libsql client is not installed" in t for t in _warn_texts())


def test_unloadable_perception_is_an_error(clean_env):
    dead = {"torch": None, "opencv": None, "numpy": None, "ultralytics": None,
            "libsql": None, "ready": False}
    assert any("Perception stack not loadable" in t for t in _warn_texts(perception=dead))


def test_clean_config_says_so(clean_env):
    assert _warn_texts() == ["No configuration problems detected."]


# --------------------------------------------------------------------- route


def test_diagnostics_route(client):
    d = client.get("/api/diagnostics").json()
    assert d["host"]["python"]
    assert len(d["config"]) > 20
    assert d["warnings"]
    assert d["running"] == []          # nothing started in this test


def test_dashboard_exposes_the_system_check(client):
    body = client.get("/").text
    assert 'id="diag"' in body
    assert "/api/diagnostics" in body


# ------------------------------------------------------------ object storage


def test_correctly_configured_aws_bucket_says_nothing(clean_env, monkeypatch):
    """Choosing Amazon is not a problem. A standing note suggesting R2 reads as
    a fault to anyone who deliberately chose AWS, and noise trains people to
    skim past the warnings that matter."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snapshots")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    texts = _warn_texts()
    assert not any("Amazon S3" in t for t in texts), texts
    assert not any("r2.cloudflarestorage" in t for t in texts), texts


def test_aws_bucket_without_region_warns(clean_env, monkeypatch):
    """'auto' would have been sent to AWS and resolved to nothing."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    texts = _warn_texts()
    assert any("no region is configured" in t for t in texts)
    # the R2 hint still belongs here, where it might be the actual explanation
    assert any("R2" in t for t in texts)


def test_aws_bucket_with_region_and_credentials_is_quiet(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    texts = _warn_texts()
    assert not any("no region is configured" in t for t in texts)
    assert not any("no AWS credentials" in t for t in texts)


def test_snapshot_bucket_accepts_the_backup_endpoint(clean_env, monkeypatch):
    """One R2 account normally serves both, so the snapshot endpoint falls back
    to the backup one rather than demanding a second copy of it."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("STRIKEE_BACKUP_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    assert not any("go to Amazon S3" in t for t in _warn_texts())


def test_turso_and_backups_together_is_not_flagged(clean_env, monkeypatch):
    """Running both is a deliberate choice - live cloud data plus a restorable
    file. Repeating that back every time the panel opens is noise, and noise is
    what makes people skim past the lines that matter."""
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    monkeypatch.setenv("STRIKEE_BACKUP_BUCKET", "strikee-snapshots")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    from app.diagnostics import config_report, warnings as warn
    perception = {"torch": "2.0.1", "opencv": "4.9", "numpy": "1.26",
                  "ultralytics": "8.3", "libsql": None, "ready": True}
    models = [{"role": "snooker", "path": "best.pt", "exists": True, "size_mb": 6.0}]
    texts = [w["text"] for w in warn(config_report(), perception, models)]
    assert texts == ["No configuration problems detected."], texts


def test_aws_bucket_without_region_warns(clean_env, monkeypatch):
    """'auto' would have been sent to AWS and resolved to nothing."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    texts = _warn_texts()
    assert any("no region is configured" in t for t in texts)
    # the R2 hint still belongs here, where it might be the actual explanation
    assert any("R2" in t for t in texts)


def test_aws_bucket_with_region_and_credentials_is_quiet(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    texts = _warn_texts()
    assert not any("no region is configured" in t for t in texts)
    assert not any("no AWS credentials" in t for t in texts)


def test_snapshot_bucket_accepts_the_backup_endpoint(clean_env, monkeypatch):
    """One R2 account normally serves both, so the snapshot endpoint falls back
    to the backup one rather than demanding a second copy of it."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("STRIKEE_BACKUP_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    assert not any("go to Amazon S3" in t for t in _warn_texts())


"""Diagnostics: does the panel tell the truth about what is in effect?

The question it answers is a Windows one - `set VAR=x` applies only to the
window it was typed in, so a setting can look configured and simply never
reach the process. Reporting the *source* of every value is the point.
"""
import os

import pytest

from app.diagnostics import config_report, model_report, warnings


@pytest.fixture
def clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("STRIKEE_", "TURSO_")):
            monkeypatch.delenv(key, raising=False)


def _by_name(cfg):
    return {c["name"]: c for c in cfg}


def test_unset_knob_reports_its_default_not_the_environment(clean_env):
    cfg = _by_name(config_report())
    k = cfg["STRIKEE_MAX_STREAMS"]
    assert k["source"] == "default"
    assert k["effective"] == 3


def test_set_knob_reports_as_environment(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_EXIT_SEC", "120")
    k = _by_name(config_report())["STRIKEE_EXIT_SEC"]
    assert k["source"] == "environment"
    assert k["effective"] == 120.0


def test_optional_knob_with_no_default_reads_unset(clean_env):
    assert _by_name(config_report())["STRIKEE_EXIT_SEC"]["source"] == "unset"


def test_unparseable_value_is_reported_not_raised(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_RATE_TABLE", "abc")
    k = _by_name(config_report())["STRIKEE_RATE_TABLE"]
    assert k["error"] and k["effective"] is None


def test_secrets_are_masked(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.super.secret.value")
    k = _by_name(config_report())["TURSO_AUTH_TOKEN"]
    assert "secret" not in k["value"]
    assert k["value"].startswith("set (")


# ------------------------------------------------------------------ warnings


def _warn_texts(cfg=None, perception=None, models=None):
    perception = perception or {"torch": "2.0.1", "opencv": "4.9", "numpy": "1.26",
                                "ultralytics": "8.3", "libsql": None, "ready": True}
    models = models if models is not None else [
        {"role": "snooker", "path": "best.pt", "exists": True, "size_mb": 6.0},
        {"role": "person", "path": "yolo11n.pt", "exists": True, "size_mb": 5.6}]
    return [w["text"] for w in warnings(cfg or config_report(), perception, models)]


def test_too_many_streams_is_an_error(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_MAX_STREAMS", "6")
    assert any("STRIKEE_MAX_STREAMS=6" in t for t in _warn_texts())


def test_three_streams_is_fine(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_MAX_STREAMS", "3")
    assert not any("MAX_STREAMS" in t for t in _warn_texts())


def test_seconds_and_ticks_together_warns_which_wins(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_EXIT_SEC", "120")
    monkeypatch.setenv("STRIKEE_EXIT_TICKS", "3")
    assert any("STRIKEE_EXIT_SEC wins" in t for t in _warn_texts())


def test_missing_model_is_an_error(clean_env):
    models = [{"role": "snooker", "path": "best.pt", "exists": False, "size_mb": None}]
    assert any("snooker model missing" in t for t in _warn_texts(models=models))


def test_turso_without_token_is_an_error(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    assert any("TURSO_AUTH_TOKEN is not" in t for t in _warn_texts())


def test_turso_without_libsql_is_an_error(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")
    assert any("libsql client is not installed" in t for t in _warn_texts())


def test_unloadable_perception_is_an_error(clean_env):
    dead = {"torch": None, "opencv": None, "numpy": None, "ultralytics": None,
            "libsql": None, "ready": False}
    assert any("Perception stack not loadable" in t for t in _warn_texts(perception=dead))


def test_clean_config_says_so(clean_env):
    assert _warn_texts() == ["No configuration problems detected."]


# --------------------------------------------------------------------- route


def test_diagnostics_route(client):
    d = client.get("/api/diagnostics").json()
    assert d["host"]["python"]
    assert len(d["config"]) > 20
    assert d["warnings"]
    assert d["running"] == []          # nothing started in this test


def test_dashboard_exposes_the_system_check(client):
    body = client.get("/").text
    assert 'id="diag"' in body
    assert "/api/diagnostics" in body


# ------------------------------------------------------------ object storage


def test_correctly_configured_aws_bucket_says_nothing(clean_env, monkeypatch):
    """Choosing Amazon is not a problem. A standing note suggesting R2 reads as
    a fault to anyone who deliberately chose AWS, and noise trains people to
    skim past the warnings that matter."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snapshots")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    texts = _warn_texts()
    assert not any("Amazon S3" in t for t in texts), texts
    assert not any("r2.cloudflarestorage" in t for t in texts), texts


def test_aws_bucket_without_region_warns(clean_env, monkeypatch):
    """'auto' would have been sent to AWS and resolved to nothing."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    texts = _warn_texts()
    assert any("no region is configured" in t for t in texts)
    # the R2 hint still belongs here, where it might be the actual explanation
    assert any("R2" in t for t in texts)


def test_aws_bucket_with_region_and_credentials_is_quiet(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    texts = _warn_texts()
    assert not any("no region is configured" in t for t in texts)
    assert not any("no AWS credentials" in t for t in texts)


def test_snapshot_bucket_accepts_the_backup_endpoint(clean_env, monkeypatch):
    """One R2 account normally serves both, so the snapshot endpoint falls back
    to the backup one rather than demanding a second copy of it."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("STRIKEE_BACKUP_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    assert not any("go to Amazon S3" in t for t in _warn_texts())


def test_turso_and_backups_together_is_not_flagged(clean_env, monkeypatch):
    """Running both is a deliberate choice - live cloud data plus a restorable
    file. Repeating that back every time the panel opens is noise, and noise is
    what makes people skim past the lines that matter."""
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    monkeypatch.setenv("STRIKEE_BACKUP_BUCKET", "strikee-snapshots")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    from app.diagnostics import config_report, warnings as warn
    perception = {"torch": "2.0.1", "opencv": "4.9", "numpy": "1.26",
                  "ultralytics": "8.3", "libsql": None, "ready": True}
    models = [{"role": "snooker", "path": "best.pt", "exists": True, "size_mb": 6.0}]
    texts = [w["text"] for w in warn(config_report(), perception, models)]
    assert texts == ["No configuration problems detected."], texts


def test_aws_bucket_without_region_warns(clean_env, monkeypatch):
    """'auto' would have been sent to AWS and resolved to nothing."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    texts = _warn_texts()
    assert any("no region is configured" in t for t in texts)
    # the R2 hint still belongs here, where it might be the actual explanation
    assert any("R2" in t for t in texts)


def test_aws_bucket_with_region_and_credentials_is_quiet(clean_env, monkeypatch):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKE")
    texts = _warn_texts()
    assert not any("no region is configured" in t for t in texts)
    assert not any("no AWS credentials" in t for t in texts)


def test_snapshot_bucket_accepts_the_backup_endpoint(clean_env, monkeypatch):
    """One R2 account normally serves both, so the snapshot endpoint falls back
    to the backup one rather than demanding a second copy of it."""
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snaps")
    monkeypatch.setenv("STRIKEE_BACKUP_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    assert not any("go to Amazon S3" in t for t in _warn_texts())


def test_push_mode_does_not_demand_the_libsql_client(clean_env, monkeypatch):
    """Push mode talks plain HTTP. Telling someone to install a native client
    they do not use is bad advice anywhere, and worse on a CPU where native
    packages were the original problem."""
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    assert not any("libsql" in t for t in _warn_texts())


def test_replica_mode_still_demands_it(clean_env, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "replica")
    texts = _warn_texts()
    assert any("libsql" in t for t in texts)
    assert any("STRIKEE_SYNC_MODE=push" in t for t in texts), "no way out offered"
