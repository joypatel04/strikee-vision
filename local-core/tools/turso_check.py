"""Check a Turso database is usable, and say which sync mode to run.

    python tools/turso_check.py libsql://your-db-org.turso.io <auth-token>

Reads nothing from .env on purpose - pass the values explicitly so you are
checking what you think you are checking.

It answers three questions in order, stopping at the first that fails:

  1. Does the host exist and does the token work?
  2. Can we CREATE, INSERT, SELECT and DROP? Push sync needs all four - it
     creates the tables on first run and upserts rows thereafter. A token that
     can read but not write passes step 1 and fails here.
  3. Are the /v1 replication endpoints served? Only embedded replicas need
     those, and many databases do not have them. Their absence is not a
     problem - it just means STRIKEE_SYNC_MODE=push rather than replica.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

TIMEOUT = 20


def pipeline(endpoint, token, statements):
    """Run statements in one request. Returns (ok, results_or_error)."""
    requests = [{"type": "execute", "stmt": s} for s in statements]
    requests.append({"type": "close"})
    req = urllib.request.Request(
        endpoint, data=json.dumps({"requests": requests}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    for result in payload.get("results", []):
        if result.get("type") == "error":
            return False, (result.get("error") or {}).get("message", "unknown")[:200]
    return True, payload.get("results", [])


def probe(host, token, path):
    req = urllib.request.Request(f"https://{host}{path}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    url, token = sys.argv[1], sys.argv[2]
    host = url.replace("libsql://", "").replace("https://", "").rstrip("/")
    endpoint = f"https://{host}/v2/pipeline"

    print(f"host  : {host}")
    shape = "looks like a JWT" if token.count(".") == 2 else \
            "NOT JWT-shaped - is this a database token, not a platform API token?"
    print(f"token : {len(token)} chars, {shape}")
    print()

    # --- 1. reachable and authenticated ----------------------------------
    ok, detail = pipeline(endpoint, token, [{"sql": "select 1"}])
    if not ok:
        print(f"FAILED at step 1 - connect and authenticate\n  {detail}\n")
        if "404" in str(detail) or "Host not found" in str(detail):
            print("  No database at that hostname. The URL is wrong, the database was")
            print("  deleted, or it is in a different Turso organisation. Copy the URL")
            print("  from the database's Connect panel - do not assemble it by hand.")
            print("  (nslookup proves nothing here: *.turso.io is wildcard DNS, so")
            print("  every hostname resolves whether or not a database exists.)")
        elif "401" in str(detail) or "403" in str(detail):
            print("  The database exists but this token is not valid for it. Use a")
            print("  DATABASE auth token from the Connect panel, not a platform API")
            print("  token, and check the two belong to the same database.")
        return 1
    print("[ok]   connect + authenticate")

    # --- 2. can we actually write? ---------------------------------------
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    table = "strikee_sync_check"
    ok, detail = pipeline(endpoint, token, [
        {"sql": f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, ts TEXT)"},
        {"sql": f"INSERT OR REPLACE INTO {table} (id, ts) VALUES (?, ?)",
         "args": [{"type": "text", "value": "probe"},
                  {"type": "text", "value": stamp}]},
        {"sql": f"SELECT ts FROM {table} WHERE id = ?",
         "args": [{"type": "text", "value": "probe"}]},
        {"sql": f"DROP TABLE {table}"},
    ])
    if not ok:
        print(f"[FAIL] create / insert / select / drop\n         {detail}\n")
        print("  Push sync creates its tables on first run and upserts rows after,")
        print("  so it needs all four. A read-only token gets this far and no")
        print("  further - issue one with write access.")
        return 1
    print("[ok]   create + insert + select + drop  (push sync will work)")

    # --- 3. replication endpoints (optional) ------------------------------
    replica = {p: probe(host, token, p) for p in ("/version", "/v1/info", "/v1/export")}
    available = any(c and 200 <= c < 300 for c in replica.values())
    for path, code in replica.items():
        print(f"{'[ok]  ' if code and 200 <= code < 300 else '[--]  '} {path} -> {code}")

    print()
    print("=" * 62)
    if available:
        print("Both modes work. Either is fine:")
        print("  STRIKEE_SYNC_MODE=push       local SQLite authoritative, rows")
        print("                               pushed over HTTP (no libsql needed)")
        print("  STRIKEE_SYNC_MODE=replica    libsql embedded replica")
    else:
        print("Use PUSH mode. Put this in .env:")
        print()
        print("  STRIKEE_SYNC_MODE=push")
        print(f"  TURSO_DATABASE_URL=libsql://{host}")
        print("  TURSO_AUTH_TOKEN=<your token>")
        print()
        print("This database does not serve the /v1 replication endpoints, so an")
        print("embedded replica cannot sync against it - that is what the")
        print("'failed to pull db export status 404' error was. Push mode does not")
        print("use them and keeps the same guarantee that matters: local SQLite")
        print("stays the source of truth, so the box records through an outage.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
