"""Documentation drifts silently. These keep it honest.

A setting that exists but is undocumented is invisible; one that is documented
but unwired is worse, because someone sets it and believes it did something -
which is exactly what happened with STRIKEE_SCREEN_LUM.
"""
import re
from pathlib import Path

from app.diagnostics import _KNOBS

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"`(STRIKEE_[A-Z_0-9]+|TURSO_[A-Z_]+)`")


def _readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_setting_is_documented():
    registered = {k[0] for k in _KNOBS}
    documented = set(NAME.findall(_readme()))
    missing = sorted(registered - documented)
    assert not missing, f"settings the code reads but README never mentions: {missing}"


def test_readme_invents_no_settings():
    registered = {k[0] for k in _KNOBS}
    documented = {n for n in NAME.findall(_readme()) if n.startswith(("STRIKEE_", "TURSO_"))}
    phantom = sorted(documented - registered)
    assert not phantom, f"README documents settings nothing reads: {phantom}"


def test_every_documented_tool_exists():
    readme = _readme()
    for tool in set(re.findall(r"tools/(\w+\.py)", readme)):
        assert (ROOT / "tools" / tool).is_file(), f"README names a missing tool: {tool}"


def test_referenced_documents_exist():
    readme = _readme()
    for doc in set(re.findall(r"\]\((([A-Z-]+)\.md)\)", readme)):
        assert (ROOT / doc[0]).is_file(), f"README links to a missing file: {doc[0]}"


def test_env_example_only_mentions_real_settings():
    """The .env template is copied verbatim, so a phantom there ships to the box."""
    registered = {k[0] for k in _KNOBS}
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    used = set(re.findall(r"^#?\s*(STRIKEE_[A-Z_0-9]+|TURSO_[A-Z_]+)=", text, re.M))
    phantom = sorted(used - registered)
    assert not phantom, f".env.example offers settings nothing reads: {phantom}"
