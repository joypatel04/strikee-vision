# Setting up the venue box from scratch

Follow this in order. Each step ends with a check — if the check fails, stop
there. Almost every hour lost so far was spent building on top of a step that
had quietly not worked.

The one rule behind the ordering: **whatever creates `strikee.db` first decides
what kind of database it is.** Configure the cloud before drawing zones, or the
replica cannot adopt the file and you start again.

---

## 0. Before you begin

| You need | Notes |
|---|---|
| `best.pt` | **6 MB, irreplaceable.** `*.pt` is gitignored, so a clone never has it. SHA256 `d5b77ec7f3c9ce3a5f7b89b405b59b4f7e6737802fb348eab45964ed8b4a1de6` |
| `yolo11n.pt` | Optional — Ultralytics downloads it on first use. |
| Turso URL + token | From the database's **Connect** panel. A *database* token, not a platform API token. |
| AWS S3 bucket + IAM key | `s3:PutObject` only. Region e.g. `ap-south-1`. |
| DVR RTSP URL | `rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=N&subtype=0` — URL-encode `@` in the password as `%40`. |

If you are starting over on a box that has been used, clear it first:

```powershell
.venv\Scripts\python.exe tools\fresh_start.py          # shows what it would remove
.venv\Scripts\python.exe tools\fresh_start.py --yes    # removes it
```

Stop `strikee-core` first or Windows holds the files open.

---

## 1. Network — two adapters, two jobs

| Adapter | Connects to | Configuration |
|---|---|---|
| `Wi-Fi` | the extender | Static `192.168.0.50 / 255.255.255.0`, **gateway blank**, DNS blank |
| `Wi-Fi 2` | Airtel | DHCP, normal |

The blank gateway is what stops the camera adapter competing to be the route to
the internet. Windows will label it "No internet" — correct, ignore it.

Also set once, on the camera adapter: **Device Manager → Power Management →
uncheck "Allow the computer to turn off this device"**, or cameras go grey
overnight.

**Check:**

```powershell
ping 192.168.0.108
ping 8.8.8.8
Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Format-Table InterfaceAlias, NextHop
```

Both pings replying, and **exactly one** default route via `Wi-Fi 2`.

---

## 2. Python and the stack

**Python 3.11 — not 3.12.** This box is a 2011 Sandy Bridge CPU with no AVX2,
and modern PyTorch aborts on it during import with a native crash and no Python
traceback. The oldest torch with 3.12 wheels still fails, so 3.11 is not
optional.

```powershell
winget install Python.Python.3.11
```

Then, from `local-core`:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[perception,desktop]"
.venv\Scripts\python.exe -m pip install --force-reinstall "torch==2.0.1" "torchvision==0.15.2" --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install "numpy<2"
.venv\Scripts\python.exe -m pip install boto3 libsql
```

The pins come last deliberately — the extras pull modern versions of both, and
torch 2.0.1 predates NumPy 2's C API.

**Always use `.venv\Scripts\python.exe -m pip`, never bare `pip`.** Bare `pip`
resolves to system Python 3.12 and installs somewhere the app never looks.

**Check:**

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -c "import torch, numpy, cv2, boto3, libsql; print('OK', torch.__version__, numpy.__version__)"
```

`Python 3.11.x`, then `OK 2.0.1 1.26.x`. If `import torch` crashes without a
traceback, the venv is not 3.11.

*(If the Visual C++ runtime is missing: `winget install Microsoft.VCRedist.2015+.x64`, then reboot.)*

---

## 3. Models

Copy `best.pt` (and `yolo11n.pt` if you have it) into `local-core\`, beside
`pyproject.toml`.

**Check:**

```powershell
certutil -hashfile best.pt SHA256
```

Must match the hash in step 0. A truncated download fails later as a confusing
model-loading error rather than an obvious one.

---

## 4. `.env` — before anything creates the database

```powershell
copy .env.example .env
notepad .env
```

```ini
STRIKEE_MAX_STREAMS=2
STRIKEE_EXIT_SEC=120
STRIKEE_DEBUG=1

TURSO_DATABASE_URL=libsql://your-db-org.turso.io
TURSO_AUTH_TOKEN=ey...
STRIKEE_TURSO_SYNC_SEC=15

STRIKEE_S3_BUCKET=strikee-snapshots
AWS_DEFAULT_REGION=ap-south-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

`set VAR=x` applies only to the window you type it in. The `.env` file is read
every time the app starts, from any shell, shortcut or scheduled task — which is
the only thing that works for an unattended box.

**Check Turso before trusting it:**

```powershell
.venv\Scripts\python.exe tools\turso_check.py libsql://your-db-org.turso.io <token>
```

`HTTP 200` plus a sync endpoint that answers. A 404 means no database at that
hostname (`nslookup` proves nothing — `*.turso.io` is wildcard DNS). A 401 means
the token belongs to a different database.

---

## 5. The gate — prove the configuration is live

```powershell
.venv\Scripts\strikee-doctor.exe --model best.pt --rtsp "rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=1&subtype=0"
```

**Read the model line specifically.** It must say OK, not FAIL — a run that
finishes is not a run that passed.

Then:

```powershell
.venv\Scripts\strikee-core.exe
```

Open `http://127.0.0.1:8760/` → **System check**:

- Every setting from `.env` reads **`env file`**, not `default`
- **No red warnings** — it catches a missing region, absent credentials, missing
  boto3, Turso without libsql, a too-high stream cap
- `torch 2.0.1`, `numpy 1.26.x`, both models present
- Database row shows the cloud backend

**Stop here if any of that is wrong.** Everything after this builds on it.

Then stop the app.

---

## 6. Survey the cameras before drawing anything

Twelve channels, and only some are useful. More importantly, **a camera angle
can defeat the model while looking perfectly fine to you** - the overhead table
cameras show people clearly and produce zero person detections, because the
model was never trained looking down at heads. Draw six station zones against
such a camera and you get a system that reports an empty room all evening with
no clue why.

```
.venv\Scripts\python.exe tools\survey_cameras.py --url "rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel={ch}&subtype=0" --channels 1-12
```

Keep `{ch}` literal - the tool substitutes each channel. It writes an annotated
frame per channel to `survey\` (green boxes = people with their feet marked,
orange = balls) and prints what it found.

**Then open the images.** The counts alone mislead:

- A gaming camera with people in shot but `people=0` cannot drive occupancy. No
  zone fixes that; look for a lower or wider camera covering the same stations.
- `people=0` on an empty room means nothing. Re-run with someone standing there.
- Balls on a channel you thought was a people camera means the numbering is
  crossed.

Known from the July survey: **channels 1, 4, 6** are the trained top-down table
angle (ch6 sees two tables); **2, 3, 5** are the opposite end and detect badly;
**7-8** are the passage and entrance. Confirm the gaming channels here.

## 7. Zones

Once per channel, **same `--venue` every time** — that is what keeps them in one
venue:

```powershell
.venv\Scripts\python.exe field_setup.py --source "rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=1&subtype=0" --venue "Strikee Club" --source-name "Channel 1"
```

Then `channel=4`, then `channel=6`.

**Drawing:** click the corners of the table surface — the green felt, not where
people stand → click the image window → press **`n`** → **switch to PowerShell
and type the name**, press Enter (the window freezes until you do; that is the
prompt waiting) → repeat → press **`s`** when every polygon is green and no
yellow dots remain. **`q` discards everything.**

- **Channel 6 gets TWO polygons** — table 3 and table 4.
- Skip channels 2, 3 and 5 — wrong angle, the model was never trained on it.
- Runs 2 and 3 must print `reusing existing venue 'Strikee Club'`.

For the gaming lounge later, same command with `--business-unit "Gaming Lounge"
--asset-type "Gaming Station" --mode occupancy`, and the same `--venue`.

---

## 8. Run it

```powershell
.venv\Scripts\strikee-core.exe
```

Dashboard → pick **Strikee Club** → **Start pipeline**.

Within ~30 seconds you should see four tables, states changing, events arriving,
and **no banner** at the top. A banner names the fault and which adapter to look
at.

**Then the part no tooling can do for you: write down the real games on one table
by hand.** Channel 4 was the cleanest camera in the July test. Without that tally
there is nothing to judge the games log against, and you cannot rewind a live
stream.

Leave it running through normal trade. Afterwards compare:

- Games count and times against your notes
- Each game's snapshot — was it a real rack, a real end?
- Count false Occupied (empty table shown busy) and false Available

`debug_<venue>.csv` has one row per read per table showing what the model saw and
what the tracker decided. That is what explains a miscount, and what we tune
from.

---

## 9. Unattended — only once step 8 looks right

```powershell
powershell -ExecutionPolicy Bypass -File packaging\install-autostart.ps1
```

Registers a scheduled task, writes `STRIKEE_AUTOSTART_VENUE` into `.env`, and
disables sleep. Add `-Headless` for no window.

**Then enable Windows auto-login** (`netplwiz`). The task triggers at logon, not
boot — deliberately, because the cameras are on wifi and wifi is not up before a
user session exists. Without auto-login, a power cut leaves it at the lock screen
forever.

**Check:** pull the power, plug it back in, walk away for five minutes, then open
the dashboard from your phone. Tracking should have resumed on its own.

---

## Things that have already cost an evening

- **Bare `pip`** installs into system Python 3.12, not the venv.
- **Python 3.12** cannot run torch on this CPU, and downgrading torch does not
  help — 3.11 is required.
- **`set VAR=x`** dies with the window. Use `.env`.
- **LAN 1 on the Airtel router** serves no DHCP. Do not plug the PC in there.
- **`nslookup` on a Turso host** always succeeds. It proves nothing.
- **Drawing zones before configuring Turso** makes a database the replica cannot
  adopt. There is no repair.
- **The zone editor's `n` key** prompts in the terminal, not the image window.
