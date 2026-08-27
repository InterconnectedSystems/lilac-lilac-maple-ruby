# Mist Disconnect Console

Client disconnect RCA for **Juniper Mist**. Paste an Observer (read-only) API token, pick a site and client MAC, and get a verdict that correlates RF, 802.11 reason codes, DHCP/DNS after roam, Marvis, and the serving AP’s Radio Management occupancy — without dumping the whole site.

Two ways to run it:

| | What | Requirements |
|---|---|---|
| **Python** | One stdlib script; opens a local browser app | Python 3.10+ |
| **Web** | Same UI as a Vite / React app | Node 22+ |

Click **Run sample investigation** on the home page to walk the demo with no token.

![TypeScript](https://img.shields.io/badge/TypeScript-React-3178C6) ![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Mist](https://img.shields.io/badge/Mist_API-GET_only-0B7A75) ![Token](https://img.shields.io/badge/Token-Observer_read--only-8FD0C4)

---

## Install and run (Python)

No pip packages. Windows, macOS, and Linux.

```bash
git clone https://github.com/InterconnectedSystems/lilac-lilac-maple-ruby.git
cd lilac-lilac-maple-ruby

# Windows
py -3 mist_disconnect_console.py

# macOS / Linux
python3 mist_disconnect_console.py
```

It opens `http://127.0.0.1:8765/`. Ctrl+C stops the server. The API token is sent from the browser to this process, then to Mist over HTTPS GET — it is not written to disk.

```bash
python3 mist_disconnect_console.py --self-test
```

---

## Install and run (web)

```bash
git clone https://github.com/InterconnectedSystems/lilac-lilac-maple-ruby.git
cd lilac-lilac-maple-ruby
npm install
npm run dev
```

Open the URL Vite prints (default `http://127.0.0.1:8080/`). Click **Run sample investigation**, or paste an Observer token and diagnose a real MAC.

```bash
npm test          # occupancy + correlation unit tests
npx tsc --noEmit  # typecheck
```

---

## Screenshots

Captured from the built-in sample investigation (Sample HQ — Floor 2).

### Home — Observer token gate

| Desktop | iPhone |
|---|---|
| ![Home page with API region, Observer token field, and Run sample investigation](screenshots/01-home.png) | ![Mobile home with Standard practice and sample investigation](screenshots/10-home-mobile.png) |

The console only issues **GET** requests. Use an Observer / read-only token from **Organization → Settings → API Tokens**. Org Admin and write-enabled keys do not belong here.

### Investigation board

![Sample investigation: live monitor controls, Critical verdict, coverage plus DHCP after roam](screenshots/09-live.png)

| Verdict | Phone fold |
|---|---|
| ![Critical score 86 — coverage + DHCP after roam](screenshots/03-verdict.png) | ![Mobile board with RSSI −81 dBm flashing](screenshots/12-board-mobile-fold.png) |

### Correlated causes

![Correlated causes: coverage-driven disconnects, DHCP after roam, 4-way handshake, AP ping-pong, adjacent-channel non-Wi-Fi](screenshots/04-correlations.png)

Each card is a **multi-signal** pattern (not a single counter): RF band vs 802.11 reason, L3 failure in the two minutes after join/roam, ping-pong, handshake timeout, and adjacent-channel non-Wi-Fi from the occupancy histogram.

### Current radio values (occupancy)

Same stacked histogram Mist shows under **Site → Radio Management → Current Radio Values**, for the AP this client spent most of the time on (Marvis name match, else longest session).

![Channel occupancy stacked bars: teal External APs, orange Site APs, red Non-Wi-Fi. Serving channel in bold. UNII filters.](screenshots/05-occupancy.png)

| Color | Meaning |
|---|---|
| **Orange** | Site APs — this site’s radios on the channel |
| **Teal** | External APs — other-SSID / other-RSSI Wi-Fi |
| **Red** | Non-Wi-Fi interference |

Serving channel is **bold**. Bars flash when Non-Wi-Fi ≥ 30% or total occupancy ≥ 70%. UNII-1 / UNII-2 / UNII-2 Ext / UNII-3 chips filter the histogram. Live `radio_stat` utilization stays in the AP table — it is **not** mixed into the RRM bars.

### Event timeline and Marvis

| Client events | Marvis |
|---|---|
| ![Event timeline with DHCP timeout, deauth reason 4 inactivity, 4-way handshake timeout reason 15](screenshots/07-events.png) | ![Marvis text naming the demo AP the client used most of the time](screenshots/08-marvis.png) |

802.11 reason codes are decoded in place (`4` inactivity, `15` 4-way handshake timeout). Marvis `connected to <AP> most of the time` is matched to inventory (name, MAC suffix) so occupancy is pulled for that AP.

### Full board

![Full sample investigation board including occupancy, RSSI/SNR tiles, identity, sessions, events, and Marvis](screenshots/02-board.png)

---

## What it does

1. **Connect** — Select the Mist region (default `api.gc2.mist.com`) and paste an Observer token. `/self` validates the org; sites are listed from privileges.
2. **Scope** — Pick org, site, client MAC, and lookback (`1h` / `6h` / `1d` / `1w`).
3. **Diagnose** — Pull per-MAC stats, events, sessions, Marvis troubleshoot, AP inventory, and that AP’s RRM current radio values.
4. **Verdict** — Score + primary cause + notes, with correlated causes ranked by confidence.
5. **Live monitor** — Re-query every 3 / 15 / 30 / 60 seconds (RSSI/SNR sparklines, occupancy included). Auto-pauses on Mist HTTP 429.

The sample investigation is the same board with synthetic Sample HQ data — use it to learn the layout before pointing at a real site.

---

## What gets correlated

| Signal | Why it matters |
|---|---|
| RSSI / SNR vs deauth reason | Coverage (`reason 4` idle at −81 dBm) vs a clean idle timeout vs handshake failure |
| DHCP / DNS in the 2 minutes after roam or assoc | L3 broken after an 802.11 join |
| AP ping-pong and 5 → 2.4 band drops | Sticky / oscillating client |
| Short sessions and TX retries | Airtime or sticky-low-PHY |
| Serving-AP occupancy | Site vs external vs **non-Wi-Fi**; adjacent-channel non-Wi-Fi when a neighbor (±16 channels) is ≥ 50% non-Wi-Fi |
| Marvis narrative | Names the AP the client used most of the time so occupancy is the right radio |

---

## Occupancy vs the Mist portal

The histogram is **this AP’s 20-minute RRM scan** (`/sites/{id}/rrm/current/devices/{device}/band/{band}`), not site-wide channel scores and not live `radio_stat` overlaid on the serving channel.

- `wifi` / `non_wifi` occupancy fractions from RRM considerations
- Orange **Site APs** reconstructed from this site’s inventory radios on each channel
- Teal **External APs** from other-SSID / other-RSSI Wi-Fi
- Red **Non-Wi-Fi** from `non_wifi`
- Integer percents from `radio_stat` (`util_tx: 1` = 1%) stay in the AP table; RRM floats (`non_wifi: 1.0` = 100%) feed the bars

If Marvis does not name an AP, the console falls back to the longest session (then event count / live stats) and notes that on the panel.

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

No configuration is written. The token stays in the browser tab, is forwarded only to the Mist region you select, and is never stored in a database. Close the tab when finished; rotate the token if it was exposed.

Observer still sees client identifiers (MAC, hostname, username). Treat captures as operational data.

---

## Token practice

- Create the key under **Organization → Settings → API Tokens** with **Observer** (or equivalent read) privileges, scoped to the org or site you are troubleshooting.
- Default region is `api.gc2.mist.com`. Switch the API region dropdown if your org lives elsewhere (`api.mist.com`, `api.eu.mist.com`, …).
- Never paste Org Admin, Super User, or write-enabled keys into this console.

---

## Repo layout

```
mist_disconnect_console.py   Python app (stdlib only) — start here
src/components/console/      Web UI
src/lib/mist/                Mist GET client, occupancy, Marvis AP match, verdict
screenshots/                 README captures of the sample investigation
```
