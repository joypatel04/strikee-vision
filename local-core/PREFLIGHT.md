# Pre-flight — Windows venue box

One page for the club floor. The long explanations live in `FIELD-TEST.md`;
this is only what to do, in order, and how to tell it worked.

---

## A. Pack before you leave (do this at home)

`*.pt` and `*.db` are **gitignored** — a `git clone` on the club PC arrives with
**no model at all**. Nothing works without these on a USB stick:

| File | Size | Why |
|---|---|---|
| `local-core/best.pt` | 6 MB | **The product.** Custom snooker model, 9 classes (reds, colours, `game_start`, player). Without it there is no detection. |
| `local-core/yolo11n.pt` | 5 MB | Person detection (footfall / occupancy). |
| `local-core/strikee.db` | 200 KB | *Optional.* Carries the venue + zones so you don't re-draw them on site. |
| the repo itself | — | Zip it, or `git clone` on the box and copy the two `.pt` files in afterwards. |

Also worth having: the Python 3.12 installer downloaded (club wifi may be slow),
and your Turso URL + token written down.

---

## B. Network — the dual-homed PC

The PC has **two** networks: Wi-Fi to the extender for the **cameras**, Ethernet
from the Airtel router for the **internet**. Both will try to be the default
route. Fix it or the internet silently dies.

- [ ] **Wi-Fi adapter → static IP, gateway BLANK**
      `192.168.0.50` / `255.255.255.0` / gateway *(empty)* / DNS *(empty)*
      Pick an address outside the club router's DHCP pool. Windows will label it
      "No internet" — that is correct.
- [ ] **Ethernet adapter → DHCP as normal** (Airtel router, carries internet).
- [ ] `route print` → exactly **one** `0.0.0.0` default route, via the Airtel gateway.
- [ ] `ping 192.168.0.108` succeeds.
- [ ] `netsh wlan show interfaces` → note **Signal %**. Above ~70% good;
      below ~50% set `STRIKEE_MAX_STREAMS=2` and raise `STRIKEE_RATE_TABLE`.
- [ ] **Wi-Fi power saving OFF** — Device Manager → Wi-Fi adapter → Power
      Management → uncheck *"Allow the computer to turn off this device"*.
      Otherwise cameras go grey overnight.
- [ ] **DHCP reservation for the DVR** on the club router, so `192.168.0.108`
      never moves. Every RTSP URL hardcodes it; a new lease looks like a code bug.

---

## C. Install — one command

From `local-core\`:

Set the stream URL once (the quotes around the whole assignment matter — the
URL contains `&`, which cmd would otherwise treat as a command separator):

```bat
set "RTSP=rtsp://USER:PASS@192.168.0.108:554/cam/realmonitor?channel=1&subtype=0"
packaging\windows-setup.bat "%RTSP%"
```

> **Credentials are not in this repo — it is public.** Substitute the real DVR
> user and password from your own notes. If the password contains `@`, URL-encode
> it as `%40`. Never commit the filled-in URL.

Checks Python, checks the models are present, builds the venv, installs
everything, then runs `strikee-doctor`.

### The go/no-go gate

`strikee-doctor` loads `best.pt`, runs **one real inference**, and decodes one
DVR frame. **All green = the box is fine.** This is the single check that matters —
an old CPU whose torch wheel refuses to run fails here, in minute five, not at
11pm. If it fails, send Claude that output verbatim; the fallback is an ONNX
Runtime path.

Reference: `best.pt` is 3.0M params (YOLOv8-nano class) and needs ~1.7
inferences/sec total across all cameras. That is a **light** load — the pipeline
grabs every 3–13s, and each grab spends ~1.7s on RTSP connection anyway.

---

## D. Configure and run

- [ ] Zones — one polygon per table, run once per channel:
      ```bat
      .venv\Scripts\python.exe field_setup.py --source "%RTSP%" --venue "Strikee Club"
      ```
      Click the **table surface** (the green), not where people stand.
      **Channel 1** → 1 table · **channel 4** → 1 table · **channel 6** → **TWO
      polygons** (table 3 snooker + table 4). Skip channels 2, 3, 5 — wrong
      angle, the model was never trained on it.
- [ ] Run with the debug log on:
      ```bat
      set STRIKEE_DEBUG=1
      .venv\Scripts\strikee-core.exe
      ```
- [ ] Dashboard at `http://127.0.0.1:8760/`, pick the venue, **Start pipeline**.
- [ ] **Write down the real games on ONE table by hand.** ch4 was the cleanest
      camera in the July test — use it as the reference. Without this tally you
      cannot judge the games log, and you can't rewind a live stream.

---

## E. Turso (only if syncing to cloud tonight)

```bat
set TURSO_DATABASE_URL=libsql://<db>.turso.io
set TURSO_AUTH_TOKEN=<token>
set STRIKEE_TURSO_SYNC_SEC=15
```

- [ ] Header badge shows **`☁ synced Ns ago`** (green), not `⚠ NOT syncing`.
- [ ] **Offline write test** — pull the Ethernet, confirm a game still records,
      plug back in, confirm it appears in Turso. If writes fail offline, stay on
      local SQLite. The box must never miss a rack because the wifi blipped.

---

## F. Judging it (the actual point of the evening)

Compare against your handwritten tally:

- Games log count + times roughly match reality?
- Open each game's **snapshot** — was it a real rack, a real end?
- Count **false Occupied** (empty table shown busy) and **false Available**
  (busy table shown free).

Tuning is all env vars — change, restart, re-observe. No code edits:

| Symptom | Knob |
|---|---|
| Games missed, `red` peaks low on a fresh rack | lower `STRIKEE_RACK_REDS` / `STRIKEE_RERACK_HIGH` |
| Extra games, `red` swings a lot | raise `STRIKEE_RERACK_JUMP` |
| Table frees up during a long pause | raise `STRIKEE_EXIT_TICKS` |
| Table stays busy after players leave | lower `STRIKEE_EXIT_TICKS` |
| Balls missed | lower sensor `conf_threshold` to 0.15 |
| Streams dropping | lower `STRIKEE_MAX_STREAMS` (3 → 2) |

`debug_<venue>.csv` has one row per tick per table — what the model saw vs what
the tracker decided. That file explains *why*, which is the knob to turn.

---

## G. Only after it works

Autostart is a *leave-it-running* concern, not a *does-it-work* concern. Don't
touch it until section F looks good. Then: `STRIKEE_AUTOSTART_VENUE`,
`STRIKEE_HEADLESS=1`, Task Scheduler ONSTART, and
`powercfg /change standby-timeout-ac 0`. Full detail in `FIELD-TEST.md`.

---

## Do NOT do these tomorrow

- **Don't downscale the stream to 640×480 or 320×320.** Generic advice for
  person detection; wrong here. Snooker balls are tiny — the 352×288 sub-stream
  already proved it destroys detection. Stay on the **main** stream; Ultralytics
  letterboxes to 640 internally already.
- **Don't install OpenVINO.** Your bottleneck is RTSP connection time, not
  inference, and this CPU predates the AVX2/VNNI instructions its speedup relies
  on. Revisit it only for footfall, which needs continuous frames.
- **Don't try footfall.** `FootfallRunner` is built and unit-tested but not yet
  wired into the app, and `field_setup.py` can't draw a counting line yet.
  Tables only tonight.
