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

try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        print(f"HTTP {resp.status} - database reachable and token accepted.")
        print("Both are fine; the problem is elsewhere.")
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
