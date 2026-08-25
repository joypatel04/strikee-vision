"""Ask Turso directly what it thinks of your URL + token.

    python turso_check.py libsql://your-db-org.turso.io  <auth-token>

Distinguishes the three failures that all look alike from inside the client:
  404 -> no database at that hostname (wrong name/org, or it was deleted)
  401 -> the database exists, the token is not valid for it
  200 -> both fine, and the problem is elsewhere
"""
import json
import sys
import urllib.error
import urllib.request

if len(sys.argv) != 3:
    print(__doc__)
    raise SystemExit(2)

url, token = sys.argv[1], sys.argv[2]
host = url.replace("libsql://", "").replace("https://", "").rstrip("/")
endpoint = f"https://{host}/v2/pipeline"

body = json.dumps({"requests": [
    {"type": "execute", "stmt": {"sql": "select 1"}},
    {"type": "close"},
]}).encode()

req = urllib.request.Request(endpoint, data=body, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
})

print(f"host  : {host}")
print(f"token : {len(token)} chars, {token.count('.')} dots "
      f"({'looks like a JWT' if token.count('.') == 2 else 'NOT a JWT - wrong token type?'})")
print()

def probe(path, method="GET"):
    """Status code for one endpoint, or a short error string."""
    r = urllib.request.Request(f"https://{host}{path}", method=method,
                               headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, resp.read(120).decode(errors="replace").strip()
    except urllib.error.HTTPError as e:
        return e.code, e.read(120).decode(errors="replace").strip()
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def sync_report():
    """The HTTP API and the embedded-replica sync API are different services on
    the same host. A database can answer one and not the other, which is exactly
    what 'pipeline works but sync 404s' means."""
    print()
    print("Embedded-replica sync endpoints (what libsql pulls from):")
    worked = False
    for path in ("/version", "/v1/info", "/v1/export", "/v1/export/0"):
        code, body = probe(path)
        mark = "ok  " if code and 200 <= code < 300 else "    "
        print(f"  {mark}{path:16} -> {code}  {body[:60]}")
        if code and 200 <= code < 300:
            worked = True
    print()
    if not worked:
        print("  None of the sync endpoints answered. This database serves the HTTP")
        print("  API but not embedded-replica replication, so libsql.connect(...)")
        print("  with sync_url cannot work against it.")
        print("  Options: create the database on an org/plan that supports embedded")
        print("  replicas, or run local-only SQLite and back the file up instead.")


try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        print(f"HTTP {resp.status} - database reachable and token accepted.")
        sync_report()
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="replace")[:300]
    print(f"HTTP {e.code}")
    if e.code == 404:
        print("  No database at that hostname. The URL is wrong, the database was")
        print("  deleted, or it lives in a different Turso organisation.")
        print("  Copy the URL from the database's own Connect panel.")
    elif e.code in (401, 403):
        print("  The database exists but this token is not valid for it.")
        print("  Use a DATABASE auth token (Connect panel / `turso db tokens create`),")
        print("  not a platform API token.")
    print(f"  server said: {detail}")
except Exception as e:
    print(f"{type(e).__name__}: {e}")
    print("  Could not reach Turso at all - check this PC's internet adapter.")
