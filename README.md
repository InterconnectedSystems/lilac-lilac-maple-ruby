# Mist Disconnect Console

Client disconnect RCA for **Juniper Mist**. Paste an Observer (read-only) API token, pick a site and client MAC, and get a verdict that correlates RF, 802.11 reason codes, DHCP/DNS, Marvis, Radio Management occupancy, **7-day radio events (including Post radar / DFS)**, and **Microsoft Teams / Zoom calls**.

**Latest: [v1.3.3](https://github.com/InterconnectedSystems/lilac-lilac-maple-ruby/releases/tag/v1.3.3)** — scoring removed; companion “Download Python console” opens the GitHub zip (Edge cannot save files from this host).

Click **Run sample investigation** on the home page to walk the demo with no token. Sample data uses fictional `DEMO-AP-F2-*` names only.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Mist](https://img.shields.io/badge/Mist_API-GET_only-0B7A75) ![Token](https://img.shields.io/badge/Token-Observer_read--only-8FD0C4) ![Release](https://img.shields.io/badge/release-v1.3.3-8FD0C4)

---

## What’s new in v1.3.3

**Download Python console** opens the GitHub zip in a new tab. The hosted site cannot save files in Edge (`Can't download — No permissions`). Unzip, then `python3 mist_disconnect_console.py`.

No engine change from v1.3.

---

## What’s new in v1.3.2

**Download Python console** saves a zip. Edge/Windows block raw `.py` downloads (“Can't download — No permissions”). Unzip, then `python3 mist_disconnect_console.py`.

No engine change from v1.3.

---

## What’s new in v1.3.1

Companion landing (and Python intro) now name the full correlation set: occupancy, 7-day Radio Management events (DFS), and Teams/Zoom. Copy states this is RCA for troublesome client disconnects — not a Wi-Fi health score.

No engine change from v1.3.

---

## What’s new in v1.3

Removed scoring mechanism as it was misleading — this app is meant to help provide RCA for troublesome client disconnect issues.

No 0–100 number, no Healthy / Degraded / Critical. The board leads with the **RCA finding** (primary cause + evidence). Same-AP DFS still gets the **Alert · session on radar AP** banner. Correlations are unchanged.

---

## What’s new in v1.2.2

Publish install fix only. No RCA engine change.

| Fix | Why |
|---|---|
| **Lockfile in sync** | A clean `npm ci` failed (`ajv` 6 vs 8). The companion site can install and publish again. |

---

## What’s new in v1.2.1

Bug fixes on the v1.2 radar store.

| Fix | Why |
|---|---|
| **One radar banner** | Mist often returns the same association twice (connect times a fraction of a second apart). One DFS hit is now one **Alert · session on radar AP** card. |
| **Radio events full screen** | Expand the 7-day table so every kept event is reachable. |
| **Diagnose fetch hint** | A busy site (lots of devices and radio events) can take up to 60 seconds. |
| **Teams timestamps** | Millisecond call start/end still overlap same-AP radar. |

---

## What’s new in v1.2

Code fixes. Same-AP radar correlation still requires a **session on the AP that took DFS**; neighbor radar is not a hit.

| Fix | Why |
|---|---|
| **RadioEventStore** | Site RRM cannot filter by AP. Correlation now looks up radars by the session AP (and `radio_stat` BSSID aliases) instead of scanning the firehose. |
| **Time-sliced fetch** | 24h / 7d lookbacks are split into windows so a radar storm in the last hour cannot hide a hit from hour 18. |
| **Scrollable client-radar panel** | Dedicated “Radar hits on this client’s APs” table. Banner and radio-event tables scroll — the matching DFS row is no longer off-screen. |
| **Open-session overlap** | Mist `disconnect: 0` is treated as still associated. RRM `ap` / `ap_mac` / BSSID aliases are accepted. |
| **Faster login and live** | Token validate is `/self` only. Live polls walk the newest hour of RRM, not the full 7-day page walk. |

Python `--self-test` covers a buried client DFS among 2,000 neighbor radars, BSSID-family match, and `disconnect: 0`.

---

## What’s new in v1.1

| Feature | Why it matters |
|---|---|
| **Alert · session on radar AP** | If a client **session** was associated to the AP that took a DFS / Post radar hit, a pulsing banner names that session and that exact radio event. Juniper’s RRM docs: the AP deauthenticates every associated station. |
| **Same-AP gate** | Radar on a neighbor, or on today’s serving AP when the client was elsewhere, is **not** a correlation. Session AP at the radar timestamp must equal the radar AP. |
| **Exact rows under the banner** | The matching session (connect / disconnect / AP / SSID / band) and the matching Radio Event (date, channel `36 → 149`, width, power, **Post radar**) are drawn under the alert — not just a paragraph. |
| **7-day Radio Events** | Same source as Mist **Site → Radio Management → Radio Events**. The API requires `band`; the console fetches `5`, `24`, and `6` in parallel (5 GHz paginated — that is where DFS lives). Labels match the portal: *Post radar*, *Interference AP non wifi*, *Scheduled site RRM*. |
| **Teams / Zoom (7 days)** | Call window, meeting id, audio/video quality. A Teams meeting in progress during same-AP Post radar is highlighted as the media failure. |
| **Full session list** | Every association in the window, newest first, scrollable table. Rows that overlapped radar on **that** AP are tagged `radar`. |
| **CLIENT_IP_ASSIGNED is OK** | DHCP Success / IP Assigned are positive events (Mist Insights). Only timed-out / denied / terminated / bad-IP are FAIL. |

![v1.1 alert: session on DEMO-AP-F2 during Post radar, with the exact session row and radio event (channel 36 → 149)](screenshots/13-radar-alert.png)

![7-day Radio Events table matching the Mist portal (Post radar, Interference AP non wifi, Scheduled site RRM)](screenshots/14-radio-events.png)

![Entire session history with the radar-overlapped association highlighted](screenshots/15-sessions.png)

![Microsoft Teams / Zoom calls for this MAC over 7 days](screenshots/16-teams.png)

---

## Install and run (Python) — this is the v1.3.3 console

No pip packages. Windows, macOS, and Linux.

```bash
git clone https://github.com/InterconnectedSystems/lilac-lilac-maple-ruby.git
cd lilac-lilac-maple-ruby
git checkout v1.3.3

# Windows
py -3 mist_disconnect_console.py

# macOS / Linux
python3 mist_disconnect_console.py
```

It opens a local browser page. Ctrl+C stops the server. The API token is sent from the browser to this process, then to Mist over HTTPS GET — it is not written to disk.

```bash
python3 mist_disconnect_console.py --self-test
```

---

## Install and run (web)

The Vite / React tree in this repo is the published companion UI. **v1.3.3 engine and UI (no health score; GitHub zip download) are in `mist_disconnect_console.py` and `src/components/console/app.tsx`.** Use the Python command above for the local RCA engine.

```bash
git clone https://github.com/InterconnectedSystems/lilac-lilac-maple-ruby.git
cd lilac-lilac-maple-ruby
git checkout v1.3.3
npm install
npm run dev
```

---

## Screenshots

Captured from the built-in **sample investigation** (Sample HQ — Floor 2, fictional APs).

### Home — Observer token gate

| Desktop | iPhone |
|---|---|
| ![Home page with API region, Observer token field, and Run sample investigation](screenshots/01-home.png) | ![Mobile home with Standard practice and sample investigation](screenshots/10-home-mobile.png) |

The console only issues **GET** requests. Use an Observer / read-only token from **Organization → Settings → API Tokens**. Org Admin and write-enabled keys do not belong here.

### Investigation board

The banner is the first thing on the board when a session was on the radar AP.

![Sample investigation: DFS session alert, RCA finding, correlated causes](screenshots/09-live.png)

| Verdict | Phone fold |
|---|---|
| ![RCA finding — Post radar on the AP this client was connected to](screenshots/03-verdict.png) | ![Mobile board](screenshots/12-board-mobile-fold.png) |

### Correlated causes

![Correlated causes: Post radar on the connected AP, Microsoft Teams during Post radar, coverage, DHCP after roam](screenshots/04-correlations.png)

Radar and Teams cards include the call name, meeting id, session AP, radar timestamp, and `pre → post` channel.

### Current radio values (occupancy)

Same stacked histogram Mist shows under **Site → Radio Management → Current Radio Values**.

![Channel occupancy stacked bars: teal External APs, orange Site APs, red Non-Wi-Fi](screenshots/05-occupancy.png)

| Color | Meaning |
|---|---|
| **Orange** | Site APs |
| **Teal** | External APs |
| **Red** | Non-Wi-Fi interference |

### Event timeline and Marvis

| Client events | Marvis |
|---|---|
| ![Event timeline](screenshots/07-events.png) | ![Marvis naming the demo AP](screenshots/08-marvis.png) |

`CLIENT_IP_ASSIGNED` shows **OK**. DHCP timed out / denied stay **FAIL**.

### Full board

![Full sample investigation board](screenshots/02-board.png)

---

## What it does

1. **Connect** — Select the Mist region (default `api.gc2.mist.com`) and paste an Observer token. `/self` validates the org.
2. **Scope** — Pick org, site, client MAC, and lookback (`1h` / `6h` / `1d` / `1w`).
3. **Diagnose** — Per-MAC stats, events, **all sessions** (paginated), Marvis, AP inventory, occupancy, **RRM events by band** (time-sliced), Teams/Zoom calls.
4. **Alert** — If a session covered a Post radar / radar-detected event **on that same AP**, the banner shows that session and that radio row.
5. **RCA finding** — Primary cause + evidence notes + same-AP radar / Teams correlations. No health score.
6. **Live monitor** — Re-query stats/events plus the newest hour of radio events. Auto-pauses on Mist HTTP 429.

---

## What gets correlated

| Signal | Gate |
|---|---|
| **Post radar / DFS on the AP this session was on** | Session `connect…disconnect` covers the radar timestamp **and** `session.ap` (or BSSID family) equals the radar AP |
| **Teams/Zoom in progress during that radar** | Call window overlaps the radar time **and** same-AP gate |
| RSSI / SNR vs deauth reason | Coverage vs idle timeout vs handshake |
| DHCP / DNS after roam or assoc | Failures only (not IP Assigned) |
| AP ping-pong and 5 → 2.4 | Sticky / oscillating client |
| Serving-AP occupancy | Site vs external vs non-Wi-Fi |
| RRM power / channel change | Client associated to that AP at the change |
| Marvis narrative | Names the AP the client used most of the time |

A radar event on a different AP than the session is **dropped**. Same channel on another AP is coincidence, not a cause.

---

## Occupancy vs the Mist portal

The histogram is **this AP’s 20-minute RRM scan** (`/sites/{id}/rrm/current/devices/{device}/band/{band}`).

Radio Events are `GET /sites/{id}/rrm/events?band={5\|24\|6}` with `start`/`end` matching the lookback (band is required; 400 `valid band is required` otherwise).

---

## API usage (GET only)

| Step | Endpoint |
|---|---|
| Validate token | `GET /self` |
| List sites | `GET /orgs/{org}/sites` |
| Live client | `GET /sites/{site}/stats/clients/{mac}` |
| Client search / events / sessions | `GET /sites/{site}/clients/search`, `.../clients/{mac}/events`, `.../clients/sessions/search` |
| Marvis | `GET /orgs/{org}/troubleshoot` |
| AP inventory + stats | `GET /sites/{site}/devices?type=ap`, `GET /sites/{site}/stats/devices` |
| Occupancy | `GET /sites/{site}/rrm/current/devices/{device}/band/{24\|5\|6}` |
| Radio events | `GET /sites/{site}/rrm/events?band={24\|5\|6}&start=&end=` |
| Teams / Zoom | `GET /sites/{site}/stats/calls/search?mac={mac}&duration=7d` |

No configuration is written. The token stays in the browser tab and is never stored in a database.

---

## Token practice

- Create the key under **Organization → Settings → API Tokens** with **Observer** privileges.
- Default region is `api.gc2.mist.com`.
- Never paste Org Admin, Super User, or write-enabled keys.

---

## Repo layout

```
mist_disconnect_console.py   v1.3.3 RCA engine (stdlib only) — start here
src/lib/mist/radio.ts        published companion radar store (same rules)
screenshots/                 sample investigation captures (fictional DEMO-AP-F2 names)
src/                         published web companion
```
