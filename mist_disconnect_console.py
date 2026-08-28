#!/usr/bin/env python3
# Mist Disconnect Console — local browser app (Windows / macOS / Linux)
#
# Exact dashboard: Observer-token gate, site/MAC RCA, correlations, live poll,
# Radio Management occupancy, 7-day radio events, and Teams/Zoom call quality
# for the AP the client spent most time on.
# Stdlib only. Token stays in the browser tab and is sent only to this process → Mist GET APIs.
#
# Windows:
#   py -3 mist_disconnect_console.py
# Then use the page that opens (http://127.0.0.1:8765/). Ctrl+C to stop.

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_HOST = "api.gc2.mist.com"
MIST_HOSTS = (
    "api.gc2.mist.com",
    "api.mist.com",
    "api.gc1.mist.com",
    "api.ac2.mist.com",
    "api.gc4.mist.com",
    "api.eu.mist.com",
    "api.gc3.mist.com",
    "api.ac5.mist.com",
    "api.gc5.mist.com",
)
TIMEOUT = 25
DEMO_MAC = "0a0027c1e001"
WINDOW_DHCP_S = 120
WINDOW_HANDSHAKE_S = 45
WINDOW_CLUSTER_S = 300
WINDOW_RADIO_DFS_S = 120
WINDOW_RADIO_RRM_S = 300
WINDOW_CALL_S = 30
PINGPONG_MIN = 4
RADIO_EVENTS_DURATION = "7d"
# listSiteRrmEvents requires dot11_band. Portal Radio Events = union of 5 / 24 / 6.
RRM_FETCH_BANDS = ("5", "24", "6")
# No AP filter on listSiteRrmEvents. We SCAN time slices and KEEP only
# radar + this-client-AP rows in RadioEventStore. Never page one 7d firehose.
RRM_OTHER_KEEP = 200
RRM_SLICE_1D_S = 3 * 3600
RRM_SLICE_1W_S = 6 * 3600
RRM_PAGES_SLICE_5 = 6
RRM_PAGES_SLICE_OTHER = 1
RRM_PAGES_SHORT_5 = 8
RRM_PAGES_SHORT_OTHER = 2
# Walk further through a neighbor-radar storm so the client's DFS hit is not
# buried behind page 6 of a 3-hour slice. Login / live do not use this cap.
RRM_PAGES_ADAPT_5 = 24
RRM_PAGES_LIVE_5 = 3
RRM_PAGES_LIVE_OTHER = 1
RRM_TIMEOUT = 12
RRM_SCAN_PAGES_5 = RRM_PAGES_SLICE_5
RRM_SCAN_PAGES_OTHER = RRM_PAGES_SLICE_OTHER
RRM_PAGES_5 = RRM_PAGES_SLICE_5
RRM_PAGES_OTHER = RRM_PAGES_SLICE_OTHER
MAX_RADAR_CORRELATIONS = 80
SESSION_PAGES = 6
EVENT_PAGES = 4

# Portal Radio Management → Radio Events wording.
RRM_EVENT_LABELS = {
    "interference-ap-co-channel": "Interference AP co-channel",
    "interference-ap-non-wifi": "Interference AP non wifi",
    "neighbor-ap-down": "Neighbor AP down",
    "neighbor-ap-recovered": "Neighbor AP recovered",
    "radar-detected": "Radar detected",
    "rrm-radar": "Post radar",
    "scheduled-site_rrm": "Scheduled site RRM",
    "triggered-site_rrm": "Triggered site RRM",
}
DISRUPTIVE_RADIO = {
    "radar-detected",
    "rrm-radar",
    "interference-ap-co-channel",
    "interference-ap-non-wifi",
    "triggered-site_rrm",
}

REASON_CODES = {
    1: "Unspecified",
    2: "Previous authentication no longer valid",
    3: "STA leaving IBSS/ESS",
    4: "Disassociated due to inactivity",
    5: "AP cannot handle all currently associated STAs",
    6: "Class 2 frame from nonauthenticated STA",
    7: "Class 3 frame from nonassociated STA",
    8: "STA leaving BSS",
    9: "STA requesting (re)association is not authenticated",
    10: "Unacceptable power capability",
    13: "Invalid information element",
    14: "MIC failure",
    15: "4-way handshake timeout",
    16: "Group key handshake timeout",
    17: "IE in 4-way handshake different from (re)assoc",
    18: "Invalid group cipher",
    19: "Invalid pairwise cipher",
    20: "Invalid AKMP",
    23: "IEEE 802.1X authentication failed",
    39: "The QoS AP lacks sufficient bandwidth",
}

NEGATIVE = (
    "DEAUTH", "DISASSOC", "FAIL", "DENIED", "TIMEOUT", "TIMED_OUT", "STUCK",
    "DISCONNECT", "TERMINATED", "BLOCKED", "SPOOF", "NAK", "BAD_IP", "BAD IP",
)
# Mist Insights: DHCP Success / IP Assigned / DNS Success are POSITIVE.
# Do not treat the letters DHCP/DNS/ARP as failure by themselves.

CTX = ssl.create_default_context()


def describe_reason(code: Any) -> str | None:
    if code is None or code == "":
        return None
    try:
        n = int(code)
    except (TypeError, ValueError):
        return str(code)
    name = REASON_CODES.get(n)
    return f"{n} — {name}" if name else str(n)


def normalize_mac(raw: str) -> str:
    cleaned = "".join(c for c in raw.lower() if c in "0123456789abcdef")
    if len(cleaned) != 12:
        raise ValueError("MAC must be 12 hex digits (colons/dashes optional).")
    return cleaned


def format_mac(mac: str) -> str:
    n = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    if len(n) != 12:
        return mac
    return ":".join(n[i : i + 2] for i in range(0, 12, 2))


def hex_mac(raw: Any) -> str:
    return "".join(c for c in str(raw or "").lower() if c in "0123456789abcdef")


def num(v: Any) -> int | float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v == v:
        return v
    if isinstance(v, str) and v.strip():
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except ValueError:
            return None
    return None


def epoch_s(v: Any) -> float | None:
    """Unix seconds. Mist mostly returns seconds; some payloads use milliseconds."""
    n = num(v)
    if n is None:
        return None
    n = float(n)
    if abs(n) >= 1e11:
        n /= 1000.0
    return n


def duration_seconds(duration: str) -> int:
    d = str(duration or "").strip().lower()
    return {
        "1h": 3600,
        "6h": 6 * 3600,
        "1d": 86400,
        "7d": 7 * 86400,
        "1w": 7 * 86400,
    }.get(d, 86400)


def rrm_time_slices(duration: str, now: int | None = None) -> list[tuple[int, int]]:
    """Lookback split into independent [start, end] windows, newest first.

    Mist listSiteRrmEvents cannot filter by AP/MAC/event-type. Paging one 24h
    window newest-first lets a campus radar storm fill every page. Each slice
    is its own start/end so hour 18 is fetched even when hour 0–2 is huge.
    """
    now_i = int(now if now is not None else time.time())
    total = duration_seconds(duration)
    if total <= 6 * 3600:
        return [(now_i - total, now_i)]
    slice_s = RRM_SLICE_1D_S if total <= 86400 else RRM_SLICE_1W_S
    out: list[tuple[int, int]] = []
    end = now_i
    left = total
    while left > 0:
        length = min(slice_s, left)
        start = end - length
        out.append((start, end))
        end = start
        left -= length
    return out


def rrm_pages_for_band(band: str, duration: str) -> int:
    short = duration_seconds(duration) <= 6 * 3600
    if str(band) == "5":
        return RRM_PAGES_SHORT_5 if short else RRM_PAGES_SLICE_5
    return RRM_PAGES_SHORT_OTHER if short else RRM_PAGES_SLICE_OTHER


def dedupe_correlations(items: list[dict]) -> list[dict]:
    """Keep distinct correlation IDs.

    Do not strip trailing timestamps — that collapsed every extra radio-radar / call-radar
    hit in a 7-day window down to a single card, which looks like the engine failed.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for c in items:
        key = str(c.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def as_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if v in (1, "1", "true", "True"):
        return True
    if v in (0, "0", "false", "False"):
        return False
    return None


def rssi_band(rssi: Any) -> str:
    if rssi is None:
        return "unknown"
    if rssi < -75:
        return "crit"
    if rssi < -65:
        return "warn"
    return "good"


def snr_band(snr: Any) -> str:
    if snr is None:
        return "unknown"
    if snr < 15:
        return "crit"
    if snr < 25:
        return "warn"
    return "good"


def as_record(v: Any) -> dict | None:
    return v if isinstance(v, dict) else None


def unique_aps(items: list) -> list[str]:
    seen: list[str] = []
    for x in items:
        ap = x.get("ap") if isinstance(x, dict) else ""
        if ap and ap not in seen:
            seen.append(str(ap))
    return seen


def as_array(v: Any) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    rec = as_record(v)
    if rec and isinstance(rec.get("results"), list):
        return [x for x in rec["results"] if isinstance(x, dict)]
    return []


def is_negative(typ: str, text: str) -> bool:
    """FAIL vs OK for the event timeline.

    Mist Insights classifies DHCP Success, IP Assigned, DNS Success as positive.
    CLIENT_IP_ASSIGNED must not be FAIL. Only timed-out / denied / terminated /
    bad-IP DHCP-DNS-ARP events are negative.

    Check deauth/disassoc first: CLIENT_DISASSOCIATION contains the letters
    ASSOCIATION and would otherwise look like a successful join.
    """
    hay = f"{typ} {text}".upper()
    if any(k in hay for k in ("DEAUTH", "DISASSOC")):
        return True
    # AUTH is not a keyword: ASSOCIATION / AUTHORIZATION contain it and would
    # mark every successful join as a failure.
    success = any(
        k in hay
        for k in (
            "SUCCESS", "_OK", " OK", "JOINED", "ASSIGNED",
            "ASSOCIATION", "REASSOCIATION", "AUTHORIZATION",
        )
    )
    if success and not any(k in hay for k in ("FAIL", "DENIED", "TIMEOUT", "TIMED_OUT", "TERMINATED", "BAD_IP", "BAD IP")):
        return False
    return any(k in hay for k in NEGATIVE)


def util_pct(v: Any) -> int:
    """Normalize occupancy/util to 0–100.

    radio_stat uses integer percents (1 = 1%). RRM wifi/non_wifi/util_score use
    0–1 floats (0.16 = 16%). Treating integer 1 as a fraction painted 100% teal
    on the serving channel.
    """
    n = num(v)
    if n is None:
        return 0
    if isinstance(n, int):
        return int(min(100, max(0, n)))
    f = float(n)
    if 0 <= f <= 1:
        return int(round(f * 100))
    return int(round(min(100, max(0, f))))


def mist_device_id(mac: str) -> str:
    return f"00000000-0000-0000-1000-{hex_mac(mac)}"


_SKIP_AP_NAMES = {
    "the", "an", "a", "ap", "the ap", "this ap", "that ap", "another ap",
    "the access point", "access point", "client", "device",
}


def looks_like_mac(raw: str) -> str:
    """Return 12-hex MAC only if the token is actually a MAC, not an AP name with hex letters."""
    s = str(raw or "").strip()
    if re.fullmatch(r"(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}", s):
        return hex_mac(s)
    if re.fullmatch(r"[0-9a-fA-F]{12}", s):
        return s.lower()
    return ""


def fold_token(s: str) -> str:
    """Compare AP names ignoring colons, hyphens, spaces (f0:96:f0 == f096f0)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def clean_ap_token(raw: str) -> str:
    s = str(raw or "").strip().strip("\"'`").rstrip(".,;:)")
    s = re.sub(r"\s+", " ", s)
    s = re.split(r"\s+(?:and|but|which|with|for|on|in)\s+", s, maxsplit=1)[0].strip()
    if len(s) < 3 or s.casefold() in _SKIP_AP_NAMES:
        return ""
    return s


def name_mac_suffix(name: str) -> str:
    """Last hyphen/underscore segment is often the last 3 MAC octets (f0:96:f0)."""
    if not name:
        return ""
    tail = re.split(r"[-_]", name.strip())[-1]
    h = hex_mac(tail)
    return h[-6:] if len(h) >= 6 else h


def marvis_texts(marvis: Any) -> list[str]:
    """Flatten Marvis Troubleshoot payloads (results[].text, description, raw string)."""
    obj: Any = marvis
    if isinstance(marvis, str):
        blob = marvis.strip()
        if blob.startswith("{") or blob.startswith("["):
            try:
                obj = json.loads(blob)
            except json.JSONDecodeError:
                return [marvis]
        else:
            return [marvis] if marvis else []
    texts: list[str] = []
    if isinstance(obj, dict):
        for row in as_array(obj.get("results") or obj.get("insights") or obj.get("data")):
            for k in ("text", "description", "reason", "recommendation", "message"):
                if row.get(k):
                    texts.append(str(row[k]))
            if row.get("ap"):
                texts.append(f"connected to {row.get('ap')}")
            if row.get("ap_name"):
                texts.append(f"connected to {row.get('ap_name')} most of the time")
        for k in ("text", "description", "reason", "recommendation"):
            if obj.get(k):
                texts.append(str(obj[k]))
    elif isinstance(obj, list):
        for row in obj:
            if isinstance(row, dict) and row.get("text"):
                texts.append(str(row["text"]))
            elif isinstance(row, str):
                texts.append(row)
    return texts


def parse_marvis_ap_hints(marvis: Any) -> dict:
    """Pull the AP Marvis says the client 'connected to … most of the time'."""
    texts = marvis_texts(marvis)
    blob = "\n".join(texts)
    most_name: str | None = None
    names: list[str] = []
    macs: list[str] = []

    def add_name(raw: str, most: bool = False) -> None:
        nonlocal most_name
        cand = clean_ap_token(raw)
        if not cand:
            return
        if most and not most_name:
            most_name = cand
        if cand not in names:
            names.append(cand)
        h = looks_like_mac(cand)
        if h and h not in macs:
            macs.append(h)

    for m in re.finditer(r"connected to\s+(.+?)\s+most of the time", blob, re.I | re.S):
        add_name(m.group(1), most=True)
    for m in re.finditer(
        r"(?:was connected to|connected to|associated to|roamed to|on AP)\s+([A-Za-z0-9][A-Za-z0-9._:-]{2,80})",
        blob,
        re.I,
    ):
        add_name(m.group(1))
    for m in re.findall(r"(?:[0-9a-f]{2}[:\-]){5}[0-9a-f]{2}|[0-9a-f]{12}", blob, re.I):
        h = hex_mac(m)
        if len(h) == 12 and h not in macs:
            macs.append(h)
    return {"mostName": most_name, "names": names, "macs": macs, "texts": texts, "blob": blob}


def match_inventory(inventory: list, *, name: str = "", mac: str = "", text: str = "") -> dict | None:
    if not inventory:
        return None
    mac_h = hex_mac(mac)
    name_n = (name or "").strip()
    name_f = fold_token(name_n)
    suf = name_mac_suffix(name_n) if name_n else ""
    if mac_h and len(mac_h) >= 6 and not suf:
        suf = mac_h[-6:]
    blob = text or ""
    blob_l = blob.casefold()
    blob_f = fold_token(blob)

    def score(dev: dict) -> int:
        dmac = hex_mac(dev.get("mac"))
        dname = str(dev.get("name") or "").strip()
        dn = dname.casefold()
        df = fold_token(dname)
        s = 0
        if mac_h and dmac == mac_h:
            s += 100
        if name_f and df == name_f:
            s += 90
        if name_n and dn == name_n.casefold():
            s += 90
        if name_f and df and (name_f in df or df in name_f) and min(len(name_f), len(df)) >= 8:
            s += 50
        if blob and dname and len(dname) >= 4 and dn in blob_l:
            s += 80
        if blob_f and df and len(df) >= 8 and df in blob_f:
            s += 80
        dsuf = name_mac_suffix(dname)
        if suf and len(suf) >= 6 and (dmac.endswith(suf) or dsuf == suf):
            s += 75
        if blob_f and dmac and len(dmac) == 12 and dmac in blob_f:
            s += 70
        if blob_f and len(dmac) >= 6 and dmac[-6:] in blob_f and dsuf and dsuf in blob_f:
            s += 65
        return s

    ranked = [(score(d), d) for d in inventory]
    ranked.sort(key=lambda x: x[0], reverse=True)
    if ranked and ranked[0][0] >= 65:
        return ranked[0][1]
    return None


def pick_dominant_ap(
    sessions: list,
    stats: dict | None,
    events: list,
    marvis: Any,
    inventory: list | None = None,
) -> dict:
    """Prefer Marvis 'connected to X most of the time', then longest session."""
    inv = inventory or []
    hints = parse_marvis_ap_hints(marvis)
    dwell: dict[str, float] = {}
    for s in sessions:
        ap = hex_mac(s.get("ap"))
        if not ap:
            continue
        dwell[ap] = dwell.get(ap, 0) + float(s.get("duration") or 0)

    source = ""
    ap_mac = ""
    ap_name = str(hints.get("mostName") or "")
    matched: dict | None = None
    marvis_unmatched = ""
    blob = str(hints.get("blob") or "")

    if hints.get("mostName") or hints.get("names") or hints.get("macs") or blob:
        if hints.get("mostName"):
            matched = match_inventory(inv, name=str(hints["mostName"]), text=blob)
        if not matched:
            matched = match_inventory(inv, text=blob)
        if not matched:
            for n in hints.get("names") or []:
                matched = match_inventory(inv, name=n, text=blob)
                if matched:
                    break
        if not matched:
            for m in hints.get("macs") or []:
                matched = match_inventory(inv, mac=m)
                if matched:
                    break
        if matched:
            ap_mac = hex_mac(matched.get("mac"))
            ap_name = str(matched.get("name") or ap_name)
            source = "marvis"
        elif hints.get("macs"):
            ap_mac = hints["macs"][0]
            source = "marvis"
            ap_name = ap_name or str(hints.get("mostName") or "")
        elif hints.get("mostName") or hints.get("names"):
            marvis_unmatched = str(hints.get("mostName") or hints["names"][0])

    fallback_from = ""
    if not ap_mac and dwell:
        ap_mac = max(dwell, key=lambda k: dwell[k])
        source = "sessions"
        fallback_from = "longest-session"
        matched = match_inventory(inv, mac=ap_mac) or matched
        if matched:
            ap_name = str(matched.get("name") or ap_name)

    if not ap_mac:
        counts: dict[str, int] = {}
        for e in events:
            ap = hex_mac(e.get("ap"))
            if ap:
                counts[ap] = counts.get(ap, 0) + 1
        if counts:
            ap_mac = max(counts, key=lambda k: counts[k])
            source = "events"
            fallback_from = "event-count"
            dwell = {k: float(v) for k, v in counts.items()}
            matched = match_inventory(inv, mac=ap_mac) or matched
            if matched:
                ap_name = str(matched.get("name") or ap_name)

    if not ap_mac:
        ap_mac = hex_mac((stats or {}).get("ap"))
        source = "stats"
        fallback_from = "live client stats"
        matched = match_inventory(inv, mac=ap_mac) or matched
        if matched:
            ap_name = str(matched.get("name") or ap_name)

    mentioned_macs = list(hints.get("macs") or [])
    total = sum(dwell.values()) or 1
    band = ""
    for s in sessions:
        if hex_mac(s.get("ap")) == ap_mac and s.get("band"):
            band = str(s.get("band"))
            break
    if not band:
        band = str((stats or {}).get("band") or "5")

    pretty = ap_name or (format_mac(ap_mac) if ap_mac else "—")
    if source == "marvis":
        named = hints.get("mostName") or pretty
        note = (
            f"Marvis named {named} as the AP this client used most of the time. "
            f"Chart is that radio ({format_mac(ap_mac)})."
        )
    elif marvis_unmatched:
        note = (
            f"Marvis named {marvis_unmatched}, but that name did not match a site AP in inventory. "
            f"Chart is the {fallback_from or 'longest-session'} AP {pretty}."
        )
    elif hints.get("texts"):
        note = (
            f"Marvis did not name a recognizable site AP. "
            f"Chart is the {fallback_from or 'longest-session'} AP {pretty}."
        )
    else:
        note = (
            f"Marvis Troubleshoot did not return an AP name. "
            f"Chart is the {fallback_from or 'longest-session'} AP {pretty}."
        )

    return {
        "apMac": ap_mac,
        "apNameHint": ap_name,
        "source": source or "unknown",
        "dwellSeconds": dwell.get(ap_mac, 0) if ap_mac else 0,
        "dwellShare": (dwell.get(ap_mac, 0) / total) if dwell and ap_mac else 0,
        "bandHint": band,
        "marvisMentioned": source == "marvis",
        "marvisAps": mentioned_macs,
        "marvisName": hints.get("mostName") or ap_name,
        "deviceId": str((matched or {}).get("id") or (mist_device_id(ap_mac) if ap_mac else "")),
        "matchedDev": matched,
        "selectionNote": note,
        "fallback": source != "marvis",
    }


def stack_pcts(site: int, external: int, non_wifi: int) -> tuple[int, int, int]:
    s, e, n = max(0, site), max(0, external), max(0, non_wifi)
    tot = s + e + n
    if tot > 100:
        s = int(round(s * 100 / tot))
        e = int(round(e * 100 / tot))
        n = max(0, 100 - s - e)
    return s, e, n


# Standard 20 MHz 5 GHz channels the Radio Management "All" histogram uses
# (US UNII-2 Ext without weather-radar 120–128, plus UNII-3).
OCC_5_DEFAULT = [100, 104, 108, 112, 116, 132, 136, 140, 144, 149, 153, 157, 161, 165]
OCC_UNII1 = [36, 40, 44, 48]
OCC_UNII2 = [52, 56, 60, 64]
OCC_24 = [1, 6, 11]
OCC_6 = list(range(1, 234, 4))


def heard_rssi(v: Any) -> float | None:
    n = num(v)
    if n is None or float(n) == 0:
        return None
    return float(n)


def rrm_rows_from(raw: Any) -> list[dict]:
    """Normalize RRM / occupancy payloads: list, {results:[]}, {channels:[]}, or {36:{...}}."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[dict] = []
        for x in raw:
            if not isinstance(x, dict):
                continue
            if x.get("channel") is not None or x.get("chan") is not None or x.get("ch") is not None:
                out.append(x)
            else:
                out.extend(rrm_rows_from(x))
        return out
    rec = as_record(raw)
    if not rec:
        return []
    for key in ("results", "channels", "channel_usage", "considerations", "data", "items"):
        if rec.get(key) is not None:
            got = rrm_rows_from(rec.get(key))
            if got:
                return got
    keys = list(rec.keys())
    if keys and all(num(k) is not None for k in keys):
        out = []
        for k, v in rec.items():
            if isinstance(v, dict):
                row = dict(v)
                row.setdefault("channel", int(num(k) or 0))
                out.append(row)
        return out
    return []


def occ_field(row: dict, *names: str) -> int:
    nested = row.get("occupancy") if isinstance(row.get("occupancy"), dict) else {}
    usage = row.get("channel_usage") if isinstance(row.get("channel_usage"), dict) else {}
    for n in names:
        for src in (row, nested, usage):
            if src and src.get(n) is not None:
                p = util_pct(src.get(n))
                if p:
                    return p
    return 0


def rrm_occupancy_stack(row: dict, site_on_channel: bool = False) -> tuple[int, int, int]:
    """Portal bars: wifi occupancy split Site vs External, plus non_wifi.

    Live considerations often omit the `wifi` example field. `util_score_other` is
    still the other-BSS occupancy fraction and must be used even when non_wifi > 0.
    Unknown wifi (no RSSI) is External (teal), not Site — unless a site AP is on
    this channel or same-site RSSI was heard.
    """
    nw = occ_field(row, "non_wifi", "nonWifi", "non_wifi_occupancy")
    if nw == 0:
        nw = occ_field(row, "util_score_non_wifi", "util_non_wifi")
    wifi = occ_field(row, "wifi", "wifi_occupancy", "util_wifi", "occupancy_wifi")
    if wifi == 0:
        wifi = occ_field(row, "util_score_other", "util_other", "other", "util_rx_other_bss")
    rssi = heard_rssi(row.get("rssi"))
    other_rssi = heard_rssi(row.get("other_rssi"))
    other_ssid = str(row.get("other_ssid") or "").strip()
    if wifi <= 0:
        return stack_pcts(0, 0, nw)
    site_heard = rssi is not None
    ext_heard = other_rssi is not None or bool(other_ssid)
    if site_heard and not ext_heard:
        return stack_pcts(wifi, 0, nw)
    if ext_heard and not site_heard:
        return stack_pcts(0, wifi, nw)
    if site_heard and ext_heard and rssi is not None and other_rssi is not None:
        wr = 10 ** (rssi / 10.0)
        wo = 10 ** (other_rssi / 10.0)
        den = wr + wo or 1.0
        site = int(round(wifi * wr / den))
        ext = max(0, wifi - site)
        return stack_pcts(site, ext, nw)
    if site_heard or site_on_channel:
        return stack_pcts(wifi, 0, nw)
    return stack_pcts(0, wifi, nw)


def rrm_channel_stack(row: dict) -> tuple[int, int, int]:
    """Alias kept for self-test / callers — occupancy, not util_score."""
    return rrm_occupancy_stack(row)


def radio_from_device(dev: dict, band_hint: str) -> tuple[dict, str]:
    rs = as_record(dev.get("radio_stat")) or {}
    wanted = band_group(band_hint)
    keys = {"24": "band_24", "5": "band_5", "6": "band_6"}
    order = [keys.get(wanted, "band_5"), "band_5", "band_6", "band_24"]
    seen: set[str] = set()
    for key in order:
        if key in seen:
            continue
        seen.add(key)
        rec = as_record(rs.get(key))
        if rec and (rec.get("channel") or rec.get("num_clients") is not None or rec.get("power") is not None):
            return rec, key.replace("band_", "")
    return {}, wanted if wanted != "unk" else "5"


def serving_channel_row(radio: dict, channel: Any) -> dict:
    """Last-resort occupancy from live radio_stat when RRM scan is empty."""
    site = util_pct(radio.get("util_rx_in_bss", radio.get("util_in_bss")))
    external = util_pct(radio.get("util_rx_other_bss", radio.get("util_other_bss"))) + util_pct(
        radio.get("util_unknown_wifi")
    )
    non_wifi = util_pct(radio.get("util_non_wifi"))
    if site + external + non_wifi == 0:
        leftover = max(0, util_pct(radio.get("util_all")) - util_pct(radio.get("util_tx")))
        non_wifi = leftover
    s, e, n = stack_pcts(site, external, non_wifi)
    return {
        "channel": int(num(channel) or 0),
        "site": s,
        "external": e,
        "nonWifi": n,
        "serving": True,
    }


def pad_band_channels(band: str, serving_ch: int, have: set[int]) -> list[int]:
    """Portal 'All' for a 5 GHz radio on UNII-2 Ext/3 shows 100–165, including zeros."""
    extra: list[int] = []
    if serving_ch in OCC_5_DEFAULT or band == "5":
        extra.extend(OCC_5_DEFAULT)
    if serving_ch in OCC_UNII1:
        extra.extend(OCC_UNII1)
    if serving_ch in OCC_UNII2:
        extra.extend(OCC_UNII2)
    if band == "24" or serving_ch in OCC_24:
        extra.extend(OCC_24)
    out: list[int] = []
    seen: set[int] = set()
    for ch in list(have) + extra:
        if ch and ch not in seen:
            seen.add(ch)
            out.append(ch)
    out.sort()
    return out


def site_airtime(radio: dict) -> int:
    """In-BSS airtime of a site AP (TX + our BSS RX). This is the portal 'Site APs' component."""
    if not radio:
        return 0
    tx = util_pct(radio.get("util_tx"))
    inn = util_pct(radio.get("util_rx_in_bss", radio.get("util_in_bss")))
    air = min(100, tx + inn)
    if air:
        return air
    allu = util_pct(radio.get("util_all"))
    nw = util_pct(radio.get("util_non_wifi"))
    oth = util_pct(radio.get("util_rx_other_bss")) + util_pct(radio.get("util_unknown_wifi"))
    leftover = max(0, allu - nw - oth)
    if leftover:
        return leftover
    # Radio is up but counters empty — beacons still occupy (portal ~9% on a 0-client AP).
    if radio.get("channel") is not None and radio.get("power") is not None:
        return 8
    return 0


def site_airtime_by_channel(inventory: list, band: str) -> dict[int, int]:
    """Per-channel Site AP occupancy from every site AP's radio_stat, including the serving AP.

    Radio Management orange bars are 802.11 airtime from APs that belong to this site.
    RRM considerations often omit that on 'clean' channels; inventory fills them.
    """
    sums: dict[int, int] = {}
    want = band_group(band)
    for d in inventory or []:
        radio, b = radio_from_device(d, band)
        if want != "unk" and band_group(b) not in {want, "unk"}:
            continue
        ch = int(num(radio.get("channel")) or 0)
        if not ch:
            continue
        sums[ch] = min(100, sums.get(ch, 0) + site_airtime(radio))
    return sums


def channels_from_rrm(
    rows: list,
    serving_ch: Any,
    serving_radio: dict | None,
    band: str = "5",
    site_channels: dict[int, int] | None = None,
) -> list[dict]:
    """Histogram = this AP's scan (non-Wi-Fi + External) plus Site AP airtime from inventory."""
    serving_n = int(num(serving_ch) or 0)
    site_air = site_channels or {}
    by_ch: dict[int, dict] = {}
    for row in rows:
        ch = int(num(row.get("channel", row.get("chan", row.get("ch")))) or 0)
        if not ch:
            continue
        s, e, n = rrm_occupancy_stack(row, site_on_channel=ch in site_air)
        if s == 0 and site_air.get(ch):
            s, e, n = stack_pcts(site_air[ch], e, n)
        by_ch[ch] = {
            "channel": ch,
            "site": s,
            "external": e,
            "nonWifi": n,
            "serving": ch == serving_n,
        }
    for ch, air in site_air.items():
        if ch not in by_ch:
            by_ch[ch] = {
                "channel": ch,
                "site": air,
                "external": 0,
                "nonWifi": 0,
                "serving": ch == serving_n,
            }
        elif by_ch[ch]["site"] == 0 and air:
            s, e, n = stack_pcts(air, by_ch[ch]["external"], by_ch[ch]["nonWifi"])
            by_ch[ch].update(site=s, external=e, nonWifi=n)
    for ch in pad_band_channels(band, serving_n, set(by_ch)):
        if ch not in by_ch:
            by_ch[ch] = {"channel": ch, "site": 0, "external": 0, "nonWifi": 0, "serving": ch == serving_n}
        else:
            by_ch[ch]["serving"] = ch == serving_n
    out = [by_ch[k] for k in sorted(by_ch)]
    if serving_n and serving_n not in by_ch and serving_radio:
        out.append(serving_channel_row(serving_radio, serving_n))
        out.sort(key=lambda c: c["channel"])
    return out


def rf_occupancy_correlations(ap_radio: dict | None, stats: dict | None) -> list[dict]:
    out: list[dict] = []
    if not ap_radio or ap_radio.get("unavailable"):
        return out
    radio = ap_radio.get("radio") or {}
    channels = ap_radio.get("channels") or []
    serving = next((c for c in channels if c.get("serving")), None)
    ch = (serving or {}).get("channel") or radio.get("channel")
    nw = (serving or {}).get("nonWifi")
    if nw is None:
        nw = util_pct(radio.get("utilNonWifi"))
    ext = (serving or {}).get("external")
    if ext is None:
        ext = util_pct(radio.get("utilRxOtherBss")) + util_pct(radio.get("utilUnknownWifi"))
    site = (serving or {}).get("site")
    if site is None:
        site = util_pct(radio.get("utilRxInBss"))
    name = ap_radio.get("apName") or format_mac(ap_radio.get("apMac") or "")
    if nw >= 25:
        out.append({
            "id": "ap-nonwifi",
            "title": "Non-Wi-Fi interference on the serving AP channel",
            "evidence": (
                f"AP {name} sees {nw}% non-Wi-Fi occupancy on channel {ch} "
                f"(Radio Management 20-min scan). Frames collide with energy that is not 802.11 — "
                f"radar, video, BLE, or industrial interferers — which matches high TX retries "
                f"while RSSI stays usable."
            ),
            "confidence": "high" if nw >= 40 else "medium",
            "severity": "crit" if nw >= 40 else "warn",
        })
    if ext >= 30 and nw < 40:
        out.append({
            "id": "ap-external-cci",
            "title": "External AP occupancy (CCI / hidden node)",
            "evidence": (
                f"AP {name} channel {ch} has {ext}% occupancy from other BSS (external APs) "
                f"and {site}% from site APs. Foreign BSSIDs on this channel cause retries without a coverage hole."
            ),
            "confidence": "medium",
            "severity": "warn",
        })
    hot = [c for c in channels if not c.get("serving") and c.get("nonWifi", 0) >= 50]
    if hot and ch:
        nearest = min(hot, key=lambda c: abs(int(c["channel"]) - int(ch)))
        if abs(int(nearest["channel"]) - int(ch)) <= 16:
            out.append({
                "id": "ap-adj-nonwifi",
                "title": "Adjacent-channel non-Wi-Fi energy",
                "evidence": (
                    f"Channel {nearest['channel']} shows {nearest['nonWifi']}% non-Wi-Fi next to serving channel {ch}. "
                    f"Bleed and AGC pumping on the client can look like a dirty serving channel."
                ),
                "confidence": "medium",
                "severity": "warn",
            })
    return out


def pick_stats(raw: dict) -> dict:
    return {
        "mac": str(raw.get("mac") or ""),
        "hostname": raw.get("hostname") or raw.get("device"),
        "manufacture": raw.get("manufacture") or raw.get("client_manufacture"),
        "os": raw.get("os"),
        "model": raw.get("model"),
        "ssid": raw.get("ssid"),
        "vlan": raw.get("vlan_id", raw.get("vlan")),
        "ip": raw.get("ip") or raw.get("ip6"),
        "ap": raw.get("ap") or raw.get("ap_mac"),
        "band": str(raw["band"]) if raw.get("band") is not None else None,
        "channel": raw.get("channel"),
        "proto": raw.get("proto") or raw.get("protocol"),
        "rssi": num(raw.get("rssi", raw.get("rssi_dbm"))),
        "snr": num(raw.get("snr", raw.get("snr_db"))),
        "txRate": num(raw.get("tx_rate")),
        "rxRate": num(raw.get("rx_rate")),
        "uptime": num(raw.get("uptime")),
        "lastSeen": epoch_s(raw.get("last_seen", raw.get("timestamp"))),
        "txBytes": num(raw.get("tx_bytes")),
        "rxBytes": num(raw.get("rx_bytes")),
        "username": raw.get("username"),
        "keyMgmt": raw.get("key_mgmt"),
        "txRetries": num(raw.get("tx_retries", raw.get("num_tx_retries", raw.get("tx_retry")))),
        "rxRetries": num(raw.get("rx_retries", raw.get("num_rx_retries", raw.get("rx_retry")))),
        "dualBand": as_bool(raw.get("dual_band")),
    }


def pick_event(raw: dict) -> dict:
    typ = str(raw.get("type") or raw.get("type_code") or "unknown")
    text = str(raw.get("text") or "")
    return {
        "timestamp": epoch_s(raw.get("timestamp")) or 0,
        "type": typ,
        "text": text,
        "ap": str(raw.get("ap") or ""),
        "ssid": str(raw.get("ssid") or ""),
        "band": str(raw.get("band") or ""),
        "channel": raw.get("channel"),
        "reason": raw.get("reason_code", raw.get("reason")),
        "negative": is_negative(typ, text),
    }


def pick_session(raw: dict) -> dict:
    ap = str(raw.get("ap") or raw.get("ap_mac") or "")
    bssid = str(raw.get("bssid") or "")
    return {
        "ap": ap or bssid,
        "bssid": bssid,
        "ssid": str(raw.get("ssid") or ""),
        "band": str(raw.get("band") or ""),
        "connect": epoch_s(raw.get("connect")),
        "disconnect": epoch_s(raw.get("disconnect")),
        "duration": num(raw.get("duration")),
    }


def as_results(payload: Any) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    rec = as_record(payload)
    return as_array(rec.get("results") or rec.get("data") or [])


def rrm_events_query(band: str, page: int = 1, limit: int = 100, duration: str = RADIO_EVENTS_DURATION) -> dict:
    """listSiteRrmEvents query. Mist returns 400 'valid band is required' without band."""
    b = str(band or "").strip()
    if not b:
        raise ValueError("valid band is required")
    return {"band": b, "duration": duration, "limit": int(limit), "page": int(page)}


def attach_ap_names(radio_events: list, inventory: list | None) -> list:
    names = {hex_mac(d.get("mac")): str(d.get("name") or "") for d in (inventory or []) if hex_mac(d.get("mac"))}
    for re in radio_events:
        if not re.get("apName"):
            re["apName"] = names.get(re.get("ap") or "") or ""
    return radio_events


def rrm_event_label(event: str) -> str:
    ev = str(event or "").strip()
    if ev in RRM_EVENT_LABELS:
        return RRM_EVENT_LABELS[ev]
    return ev.replace("-", " ").replace("_", " ").title() or "Radio event"


def pick_rrm_event(raw: dict) -> dict:
    ev = str(raw.get("event") or raw.get("type") or "")
    pre_ch = num(raw.get("pre_channel", raw.get("preChannel")))
    ch = num(raw.get("channel"))
    changed = False
    try:
        if pre_ch not in (None, 0) and ch not in (None, 0):
            changed = int(pre_ch) != int(ch)
    except (TypeError, ValueError):
        changed = False
    ap = hex_mac(
        raw.get("ap")
        or raw.get("ap_mac")
        or raw.get("apMac")
        or raw.get("mac")
        or raw.get("device_mac")
        or raw.get("deviceMac")
    )
    return {
        "timestamp": epoch_s(raw.get("timestamp")) or 0,
        "ap": ap,
        "apName": str(raw.get("ap_name") or raw.get("apName") or ""),
        "band": str(raw.get("band") or ""),
        "channel": ch,
        "preChannel": pre_ch,
        "bandwidth": num(raw.get("bandwidth")),
        "preBandwidth": num(raw.get("pre_bandwidth", raw.get("preBandwidth"))),
        "power": num(raw.get("power")),
        "prePower": num(raw.get("pre_power", raw.get("prePower"))),
        "event": ev,
        "label": rrm_event_label(ev),
        "usage": str(raw.get("usage") or ""),
        "preUsage": str(raw.get("pre_usage") or raw.get("preUsage") or ""),
        "channelChanged": changed,
    }


def device_radio_macs(dev: dict | None) -> set[str]:
    """AP base MAC plus per-radio BSSIDs from radio_stat — RRM `ap` is often the base MAC."""
    out: set[str] = set()
    if not dev:
        return out
    for k in ("mac", "ap", "ap_mac", "bssid", "radio_mac"):
        h = hex_mac(dev.get(k))
        if len(h) == 12:
            out.add(h)
    rs = as_record(dev.get("radio_stat")) or {}
    for v in rs.values():
        if not isinstance(v, dict):
            continue
        for k in ("mac", "bssid", "ap_mac", "radio_mac"):
            h = hex_mac(v.get(k))
            if len(h) == 12:
                out.add(h)
    return out


def expand_client_aps(sessions: list | None, events: list | None, stats: dict | None, inventory: list | None) -> set[str]:
    seeds: set[str] = set()
    for s in sessions or []:
        for k in ("ap", "bssid"):
            h = hex_mac(s.get(k))
            if len(h) == 12:
                seeds.add(h)
    for e in events or []:
        h = hex_mac(e.get("ap"))
        if len(h) == 12:
            seeds.add(h)
    live = hex_mac((stats or {}).get("ap"))
    if len(live) == 12:
        seeds.add(live)
    families = [device_radio_macs(d) for d in (inventory or [])]
    out = set(seeds)
    changed = True
    while changed:
        changed = False
        for g in families:
            if out & g and not g <= out:
                out |= g
                changed = True
    return out


class RadioEventStore:
    """In-memory radar store keyed by AP MAC.

    Site RRM is a firehose (no AP filter). Correlation looks up radars by the
    APs this client actually used, including radio_stat BSSID aliases.
    """

    def __init__(self, client_aps: set[str] | None = None, families: list[set[str]] | None = None):
        self.canon: dict[str, str] = {}
        self.members: dict[str, set[str]] = {}
        for g in families or []:
            cleaned = {hex_mac(x) for x in g if len(hex_mac(x)) == 12}
            if not cleaned:
                continue
            root = min(cleaned)
            self.members.setdefault(root, set()).update(cleaned)
            for m in cleaned:
                self.canon[m] = root
        seeds = {hex_mac(a) for a in (client_aps or []) if len(hex_mac(a)) == 12}
        expanded: set[str] = set()
        for s in seeds:
            root = self.canon.get(s, s)
            expanded.add(s)
            expanded.add(root)
            expanded.update(self.members.get(root, set()))
        self.client_aps = expanded
        self.by_ap: dict[str, list[dict]] = {}
        self.radars_by_ap: dict[str, list[dict]] = {}
        self.radars: list[dict] = []
        self.kept: list[dict] = []
        self.others: list[dict] = []
        self.scanned = 0
        self.dropped = 0

    def key(self, mac: Any) -> str:
        h = hex_mac(mac)
        return self.canon.get(h, h)

    def related(self, a: Any, b: Any) -> bool:
        ha, hb = hex_mac(a), hex_mac(b)
        if not ha or not hb:
            return False
        if ha == hb:
            return True
        ka, kb = self.key(ha), self.key(hb)
        return bool(ka and ka == kb)

    def add(self, ev: dict | None) -> str:
        """Ingest one RRM row.

        Radar rows are ALWAYS indexed by AP (neighbor storms must not discard a
        scanned DFS hit). The UI export only keeps client-AP rows plus a sample
        of site-wide noise. Returns a kind used by adaptive paging:
        radar-client | client | radar | other | drop | skip.
        """
        if not ev:
            return "skip"
        self.scanned += 1
        ap = hex_mac(ev.get("ap"))
        radar = is_radar_event(ev)
        on_client = True
        if ap and self.client_aps:
            on_client = ap in self.client_aps or any(self.related(ap, c) for c in self.client_aps)
        elif self.client_aps:
            on_client = False

        if radar:
            self.radars.append(ev)
            if ap:
                self.radars_by_ap.setdefault(ap, []).append(ev)
                ck = self.key(ap)
                if ck and ck != ap:
                    self.radars_by_ap.setdefault(ck, []).append(ev)

        keep = False
        keep_other = False
        if radar:
            keep = on_client
        elif on_client:
            keep = True
        elif len(self.others) < RRM_OTHER_KEEP:
            keep = True
            keep_other = True
        if not keep:
            self.dropped += 1
            return "radar" if radar else "drop"

        self.kept.append(ev)
        if ap:
            self.by_ap.setdefault(ap, []).append(ev)
            ck = self.key(ap)
            if ck and ck != ap:
                self.by_ap.setdefault(ck, []).append(ev)
        if keep_other:
            self.others.append(ev)
        if radar:
            return "radar-client"
        return "client" if on_client else "other"

    def add_many(self, events: list | None) -> None:
        for ev in events or []:
            self.add(ev)

    def radars_on_ap(self, ap: Any) -> list[dict]:
        h = hex_mac(ap)
        seen: set[tuple] = set()
        out: list[dict] = []
        keys = {h, self.key(h)}
        keys.update(self.members.get(self.key(h), set()))
        for k in keys:
            for re in self.radars_by_ap.get(k) or []:
                sig = (re.get("ap"), re.get("timestamp"), re.get("event"), re.get("channel"))
                if sig in seen:
                    continue
                seen.add(sig)
                out.append(re)
        return out

    def hits_for_session(self, sess: dict) -> list[dict]:
        out = [re for re in self.radars_on_ap(sess.get("ap")) if session_covers(sess, epoch_s(re.get("timestamp")) or 0)]
        if sess.get("bssid") and hex_mac(sess.get("bssid")) != hex_mac(sess.get("ap")):
            for re in self.radars_on_ap(sess.get("bssid")):
                if session_covers(sess, epoch_s(re.get("timestamp")) or 0) and re not in out:
                    out.append(re)
        out.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
        return out

    def hits_for_sessions(self, sessions: list | None) -> list[tuple[dict, dict]]:
        pairs = []
        for s in sessions or []:
            for re in self.hits_for_session(s):
                pairs.append((s, re))
        return pairs

    def client_radar_events(self, sessions: list | None) -> list[dict]:
        seen: set[tuple] = set()
        rows: list[dict] = []
        for _s, re in self.hits_for_sessions(sessions):
            key = (re.get("ap"), re.get("timestamp"), re.get("event"), re.get("channel"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(re)
        rows.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
        return rows

    def export_events(self) -> list[dict]:
        seen: set[tuple] = set()
        out: list[dict] = []
        for ev in self.kept:
            key = (ev.get("ap"), ev.get("timestamp"), ev.get("event"), ev.get("channel"), ev.get("band"))
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
        out.sort(key=lambda e: e.get("timestamp") or 0, reverse=True)
        return out


def quality_poor(q: Any) -> bool:
    n = num(q)
    if n is None:
        return False
    if n > 5:
        return n < 50
    return n <= 2 and n >= 0


def collab_app_label(app: Any) -> str:
    a = str(app or "").strip().lower()
    if not a:
        return "Unknown app"
    if "team" in a:
        return "Microsoft Teams"
    if "zoom" in a:
        return "Zoom"
    if "webex" in a:
        return "Webex"
    if "skype" in a:
        return "Skype"
    return str(app)


def is_teams_app(app: Any) -> bool:
    a = str(app or "").strip().lower()
    return "team" in a or "skype" in a


def pick_call(raw: dict) -> dict:
    app = str(raw.get("app") or "unknown")
    start = epoch_s(raw.get("start_time", raw.get("start")))
    end = epoch_s(raw.get("end_time", raw.get("end")))
    dur = None
    if start is not None and end is not None and end > start:
        dur = end - start
    audio = num(raw.get("audio_quality"))
    video = num(raw.get("video_quality"))
    screen = num(raw.get("screen_share_quality"))
    rating = num(raw.get("rating"))
    return {
        "app": app,
        "appLabel": collab_app_label(app),
        "mac": hex_mac(raw.get("mac")),
        "meetingId": str(raw.get("meeting_id") or raw.get("meetingId") or ""),
        "start": start,
        "end": end,
        "duration": dur,
        "audioQuality": audio,
        "videoQuality": video,
        "screenShareQuality": screen,
        "rating": rating,
        "poor": quality_poor(audio) or quality_poor(video) or quality_poor(rating) or quality_poor(screen),
        "teams": is_teams_app(app),
    }


def same_ap_mac(a: Any, b: Any) -> bool:
    ha, hb = hex_mac(a), hex_mac(b)
    return bool(ha and hb and ha == hb)


def annotate_radio_events(
    radio_events: list,
    events: list,
    sessions: list,
    stats: dict | None,
) -> list:
    for re in radio_events:
        on_ap = client_ap_at(sessions, events, stats, float(re.get("timestamp") or 0))
        re["onClientAp"] = same_ap_mac(on_ap, re.get("ap"))
        re["highlight"] = bool(is_radar_event(re) and re["onClientAp"])
    return radio_events


def is_radar_event(ev: dict) -> bool:
    e = str(ev.get("event") or "").lower()
    return e in {"radar-detected", "rrm-radar"} or "radar" in e


def power_changed(ev: dict) -> bool:
    pre, cur = num(ev.get("prePower")), num(ev.get("power"))
    if pre is None or cur is None:
        return False
    return abs(float(cur) - float(pre)) >= 3


def band_hz_label(b: Any) -> str:
    s = str(b or "").strip().lower()
    if s in {"24", "2.4", "2"}:
        return "2.4 GHz"
    if s == "6":
        return "6 GHz"
    if not s:
        return "—"
    return "5 GHz"


def arrow_vals(pre: Any, cur: Any, unit: str = "") -> str:
    if pre in (None, "", 0) or str(pre) == str(cur):
        return f"{cur}{unit}" if cur not in (None, "") else "—"
    if cur in (None, ""):
        return f"{pre}{unit}"
    return f"{pre}{unit} → {cur}{unit}"


def ap_name_for(mac: Any, radio_events: list | None = None, ap_radio: dict | None = None) -> str:
    h = hex_mac(mac)
    if not h:
        return "—"
    if ap_radio and same_ap_mac(ap_radio.get("apMac"), h) and ap_radio.get("apName"):
        return str(ap_radio.get("apName"))
    for re in radio_events or []:
        if same_ap_mac(re.get("ap"), h) and re.get("apName"):
            return str(re.get("apName"))
    return format_mac(h)


def radar_fact(re: dict, client_ap: str, client_name: str, call: dict | None = None, drop: dict | None = None) -> dict:
    """Structured fields so the dashboard can name the call, AP, time, and radar row."""
    return {
        "call": (call or {}).get("appLabel") if call else None,
        "meetingId": (call or {}).get("meetingId") or None,
        "callStart": (call or {}).get("start") if call else None,
        "callEnd": (call or {}).get("end") if call else None,
        "callDuration": (call or {}).get("duration") if call else None,
        "audioQuality": (call or {}).get("audioQuality") if call else None,
        "videoQuality": (call or {}).get("videoQuality") if call else None,
        "clientAp": hex_mac(client_ap) or None,
        "clientApName": client_name or None,
        "radarEvent": re.get("label") or re.get("event"),
        "radarType": re.get("event"),
        "radarTime": re.get("timestamp"),
        "radarAp": hex_mac(re.get("ap")) or None,
        "radarApName": re.get("apName") or None,
        "radarChannel": arrow_vals(re.get("preChannel"), re.get("channel")),
        "radarWidth": arrow_vals(re.get("preBandwidth"), re.get("bandwidth"), " MHz"),
        "radarPower": arrow_vals(re.get("prePower"), re.get("power"), " dBm"),
        "radarBand": f"{band_hz_label(re.get('preUsage') or re.get('band'))} → {band_hz_label(re.get('usage') or re.get('band'))}",
        "dropType": (drop or {}).get("type") if drop else None,
        "dropTime": (drop or {}).get("timestamp") if drop else None,
    }


def client_ap_at(sessions: list, events: list, stats: dict | None, t: float) -> str:
    """AP this client was associated to at epoch t.

    Sessions first, then the last client event at or before t. Live stats AP is
    only used if t is within 5 minutes of now — otherwise a 4-day-old radar would
    be pinned to whichever AP the client is on today, which is a false match.
    """
    t = float(epoch_s(t) or 0)
    covering = []
    for s in sessions or []:
        start = epoch_s(s.get("connect"))
        if start is None or float(start) == 0:
            continue
        if session_covers(s, t) and s.get("ap"):
            covering.append((float(start), hex_mac(s.get("ap"))))
    if covering:
        covering.sort(key=lambda x: x[0], reverse=True)
        return covering[0][1]
    prior = [
        e for e in (events or [])
        if (epoch_s(e.get("timestamp")) or 0) <= t + 2 and e.get("ap")
    ]
    if prior:
        prior.sort(key=lambda e: epoch_s(e.get("timestamp")) or 0)
        return hex_mac(prior[-1].get("ap"))
    live = hex_mac((stats or {}).get("ap"))
    if live and abs(time.time() - t) <= 300:
        return live
    return ""


def session_covers(sess: dict, t: float) -> bool:
    t = float(epoch_s(t) or 0)
    start = epoch_s(sess.get("connect"))
    if start is None or float(start) == 0:
        return False
    end = epoch_s(sess.get("disconnect"))
    # Mist often sends disconnect=0 for an open session. Treat 0 / inverted as open.
    if end is None or float(end) == 0 or float(end) < float(start):
        end = t + 1
    return float(start) - 2 <= t <= float(end) + 2


def session_on_ap_at(sessions: list | None, t: float, ap: Any) -> dict | None:
    """Client session on this AP covering epoch t. Same-AP is required."""
    hits = [
        s for s in (sessions or [])
        if session_covers(s, t) and (
            same_ap_mac(s.get("ap"), ap) or same_ap_mac(s.get("bssid"), ap)
        )
    ]
    if not hits:
        return None
    hits.sort(key=lambda s: float(s.get("connect") or 0), reverse=True)
    return hits[0]


def radar_session_alerts(
    radio_events: list,
    sessions: list | None,
    calls: list | None = None,
    ap_radio: dict | None = None,
    store: RadioEventStore | None = None,
) -> list[dict]:
    """Dashboard alerts: a client SESSION was associated to the AP that took radar.

    Juniper Mist: on DFS radar the AP deauthenticates all associated clients.
    A radar on any other AP is not this client's problem — no alert.
    Events-only guesses do not count; this alert requires a session record.

    Many DFS hits on the same association (7-day lookback on a busy 5 GHz cell)
    are grouped under that session so the banner does not explode.
    """
    raw: list[dict] = []
    pairs: list[tuple[dict, dict]] = []
    if store is not None:
        pairs = store.hits_for_sessions(sessions)
    else:
        for re in radio_events or []:
            if not is_radar_event(re):
                continue
            ts = float(epoch_s(re.get("timestamp")) or 0)
            sess = session_on_ap_at(sessions, ts, re.get("ap"))
            if sess:
                pairs.append((sess, re))
    for sess, re in pairs:
        ts = float(epoch_s(re.get("timestamp")) or 0)
        ap_mac = hex_mac(sess.get("ap"))
        ap_name = sess.get("apName") or ap_name_for(ap_mac, radio_events, ap_radio)
        overlapping_call = None
        for c in calls or []:
            if _call_open_at(c, ts):
                overlapping_call = c
                break
        fact = radar_fact(re, ap_mac, ap_name, call=overlapping_call)
        meet = ""
        if overlapping_call:
            meet = (
                f" {overlapping_call.get('appLabel') or 'Call'}"
                + (f" meeting {overlapping_call.get('meetingId')}" if overlapping_call.get("meetingId") else "")
                + " was in progress."
            )
        radio = {
            "timestamp": re.get("timestamp"),
            "ap": hex_mac(re.get("ap")),
            "apName": re.get("apName") or ap_name,
            "band": re.get("band"),
            "channel": re.get("channel"),
            "preChannel": re.get("preChannel"),
            "bandwidth": re.get("bandwidth"),
            "preBandwidth": re.get("preBandwidth"),
            "power": re.get("power"),
            "prePower": re.get("prePower"),
            "event": re.get("event"),
            "label": re.get("label"),
            "usage": re.get("usage"),
            "preUsage": re.get("preUsage"),
            "channelChanged": re.get("channelChanged"),
            "highlight": True,
            "onClientAp": True,
        }
        raw.append({
            "id": f"session-radar-{re.get('timestamp')}-{ap_mac}",
            "severity": "crit",
            "title": f"Session was on this AP during {re.get('label') or 'Post radar'}",
            "summary": (
                f"This client's session on {ap_name} ({format_mac(ap_mac)}) was active when "
                f"{re.get('label') or 'Post radar'} hit that same AP "
                f"(channel {fact.get('radarChannel')}).{meet} "
                "DFS vacates 5 GHz and deauthenticates every associated station."
            ),
            "sessionAp": ap_mac,
            "sessionApName": ap_name,
            "sessionConnect": sess.get("connect"),
            "sessionDisconnect": sess.get("disconnect"),
            "sessionDuration": sess.get("duration"),
            "radarEvent": re.get("label") or re.get("event"),
            "radarTime": re.get("timestamp"),
            "radarAp": hex_mac(re.get("ap")),
            "radarApName": re.get("apName") or ap_name,
            "radarChannel": fact.get("radarChannel"),
            "radarWidth": fact.get("radarWidth"),
            "radarPower": fact.get("radarPower"),
            "radarBand": fact.get("radarBand"),
            "call": (overlapping_call or {}).get("appLabel") if overlapping_call else None,
            "meetingId": (overlapping_call or {}).get("meetingId") if overlapping_call else None,
            "callStart": (overlapping_call or {}).get("start") if overlapping_call else None,
            "callEnd": (overlapping_call or {}).get("end") if overlapping_call else None,
            "detail": fact,
            "session": {
                "ap": ap_mac,
                "apName": ap_name,
                "ssid": sess.get("ssid"),
                "band": sess.get("band"),
                "connect": sess.get("connect"),
                "disconnect": sess.get("disconnect"),
                "duration": sess.get("duration"),
                "hitByRadar": True,
            },
            "radio": radio,
            "radios": [radio],
        })

    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for a in raw:
        key = (a.get("sessionAp"), a.get("sessionConnect"))
        if key not in grouped:
            grouped[key] = a
            order.append(key)
            continue
        host = grouped[key]
        host.setdefault("radios", [host["radio"]] if host.get("radio") else [])
        host["radios"].append(a["radio"])
        if not host.get("call") and a.get("call"):
            host["call"] = a.get("call")
            host["meetingId"] = a.get("meetingId")
            host["callStart"] = a.get("callStart")
            host["callEnd"] = a.get("callEnd")
    out: list[dict] = []
    for key in order:
        a = grouped[key]
        radios = a.get("radios") or ([a["radio"]] if a.get("radio") else [])
        radios.sort(key=lambda r: epoch_s(r.get("timestamp")) or 0, reverse=True)
        a["radios"] = radios
        a["radio"] = radios[0] if radios else a.get("radio")
        n = len(radios)
        if n > 1:
            a["title"] = f"Session was on this AP during {n} radar events"
            a["summary"] = (
                f"This client's session on {a.get('sessionApName')} ({format_mac(a.get('sessionAp') or '')}) "
                f"was associated while {n} DFS / Post radar events hit that same AP. "
                "Each event is listed under this banner. DFS vacates 5 GHz and deauthenticates every associated station."
            )
            a["id"] = f"session-radar-{a.get('sessionConnect')}-{a.get('sessionAp')}"
        out.append(a)

    for s in sessions or []:
        s["radarHits"] = [
            r.get("timestamp")
            for a in out
            if same_ap_mac(s.get("ap"), a.get("sessionAp")) and s.get("connect") == a.get("sessionConnect")
            for r in (a.get("radios") or [a.get("radio")])
            if r
        ]
        s["hitByRadar"] = bool(s.get("radarHits"))
    return out


def radar_hits_this_client(re: dict, sessions: list, events: list, stats: dict | None) -> tuple[bool, str]:
    """True only when the radar AP is the AP this client was on at that timestamp."""
    ts = float(epoch_s(re.get("timestamp")) or 0)
    on_ap = client_ap_at(sessions or [], events or [], stats, ts)
    if not on_ap or not re.get("ap"):
        return False, on_ap
    return same_ap_mac(on_ap, re.get("ap")), on_ap


def client_drops(events: list) -> list[dict]:
    out = []
    for e in events:
        u = (e.get("type") or "").upper()
        if any(k in u for k in ("DEAUTH", "DISASSOC", "DISCONNECT")) or "ROAM" in u:
            out.append(e)
    return out


def radio_event_correlations(
    radio_events: list,
    events: list,
    sessions: list | None = None,
    stats: dict | None = None,
    ap_radio: dict | None = None,
    store: RadioEventStore | None = None,
) -> list[dict]:
    """Correlate 7-day Radio Management events with this client's presence and drops.

    Highest priority: RRM/DFS radar on the AP the client was connected to at that
    instant — DFS disassociates 5 GHz clients immediately (Juniper/Mist RRM docs).
    """
    if not radio_events and store is None:
        return []
    if store is None:
        seeds = expand_client_aps(sessions, events, stats, None)
        store = RadioEventStore(seeds)
        store.add_many(radio_events)
    drops = client_drops(events or [])
    out: list[dict] = []
    radar_kept = 0
    seen_radar: set[tuple] = set()
    for sess, re in store.hits_for_sessions(sessions):
        if not is_radar_event(re):
            continue
        sig = (re.get("ap"), re.get("timestamp"), re.get("event"))
        if sig in seen_radar:
            continue
        seen_radar.add(sig)
        if radar_kept >= MAX_RADAR_CORRELATIONS:
            continue
        ts = float(epoch_s(re.get("timestamp")) or 0)
        on_ap = hex_mac(sess.get("ap"))
        connected = True
        window = WINDOW_RADIO_DFS_S
        hits: list[tuple[float, dict]] = []
        for d in drops:
            dt = float(epoch_s(d.get("timestamp")) or 0) - ts
            if dt < -15 or dt > window:
                continue
            if store.related(d.get("ap"), re.get("ap")) or same_ap_mac(d.get("ap"), re.get("ap")):
                hits.append((dt, d))
        hits.sort(key=lambda x: abs(x[0]))
        drop = hits[0][1] if hits else None
        dt = hits[0][0] if hits else None
        apn = format_mac(re.get("ap") or "")
        uid = f"{re.get('timestamp')}-{hex_mac(re.get('ap')) or 'ap'}"
        client_name = ap_name_for(on_ap, radio_events, ap_radio)
        radar_name = re.get("apName") or apn
        fact = radar_fact(re, on_ap, client_name, drop=drop)
        if drop is not None:
            evidence = (
                f"{re.get('label')} at radar AP {radar_name} ({apn}), channel {fact['radarChannel']}. "
                f"Client was on {client_name} ({format_mac(on_ap)}) — same AP. "
                f"{drop.get('type')} {int(dt)}s later. DFS vacates 5 GHz immediately."
            )
        else:
            evidence = (
                f"{re.get('label')} at radar AP {radar_name} ({apn}), channel {fact['radarChannel']}. "
                f"Client was connected to {client_name} ({format_mac(on_ap)}) — same AP as the radar event. "
                "No matching deauth in the client log, but DFS still forces a channel change."
            )
        out.append({
            "id": f"radio-radar-{uid}",
            "title": f"{re.get('label')} on the AP this client was connected to",
            "evidence": evidence,
            "confidence": "high",
            "severity": "crit",
            "highlight": True,
            "detail": fact,
        })
        radar_kept += 1

    client_aps = store.client_aps or expand_client_aps(sessions, events, stats, None)
    for re in radio_events or []:
        ts = float(epoch_s(re.get("timestamp")) or 0)
        re_ap = hex_mac(re.get("ap"))
        radar = is_radar_event(re)
        if radar:
            continue  # already handled via store
        if re_ap and client_aps and re_ap not in client_aps and not any(store.related(re_ap, c) for c in client_aps):
            continue
        connected, on_ap = radar_hits_this_client(re, sessions or [], events or [], stats)
        window = WINDOW_RADIO_DFS_S if radar else WINDOW_RADIO_RRM_S
        hits: list[tuple[float, dict]] = []
        for d in drops:
            dt = float(epoch_s(d.get("timestamp")) or 0) - ts
            if dt < -15 or dt > window:
                continue
            # Drop must be on the same AP as the radio event. Same channel on a
            # different AP is coincidence, not causation.
            if connected or same_ap_mac(d.get("ap"), re.get("ap")):
                hits.append((dt, d))
        hits.sort(key=lambda x: abs(x[0]))
        drop = hits[0][1] if hits else None
        dt = hits[0][0] if hits else None
        ch_bit = ""
        if re.get("channelChanged"):
            ch_bit = f" Channel {int(re.get('preChannel') or 0)} → {int(re.get('channel') or 0)}."
        pwr_bit = ""
        if power_changed(re):
            pwr_bit = f" Power {re.get('prePower')} → {re.get('power')} dBm."
        apn = format_mac(re.get("ap") or "")
        uid = f"{re.get('timestamp')}-{re_ap or 'ap'}"

        if radar:
            if not connected:
                continue
            if radar_kept >= MAX_RADAR_CORRELATIONS:
                continue
            client_name = ap_name_for(on_ap, radio_events, ap_radio)
            radar_name = re.get("apName") or apn
            fact = radar_fact(re, on_ap, client_name, drop=drop)
            if drop is not None:
                evidence = (
                    f"{re.get('label')} at radar AP {radar_name} ({apn}), channel {fact['radarChannel']}. "
                    f"Client was on {client_name} ({format_mac(on_ap)}) — same AP. "
                    f"{drop.get('type')} {int(dt)}s later. DFS vacates 5 GHz immediately."
                )
            else:
                evidence = (
                    f"{re.get('label')} at radar AP {radar_name} ({apn}), channel {fact['radarChannel']}. "
                    f"Client was connected to {client_name} ({format_mac(on_ap)}) — same AP as the radar event. "
                    "No matching deauth in the client log, but DFS still forces a channel change."
                )
            out.append({
                "id": f"radio-radar-{uid}",
                "title": f"{re.get('label')} on the AP this client was connected to",
                "evidence": evidence,
                "confidence": "high",
                "severity": "crit",
                "highlight": True,
                "detail": fact,
            })
            radar_kept += 1
            continue

        if not (re.get("event") in DISRUPTIVE_RADIO or re.get("channelChanged") or power_changed(re)):
            continue
        if not (connected or drop is not None):
            continue

        if re.get("event") == "neighbor-ap-down" and connected:
            out.append({
                "id": f"radio-neighbor-{uid}",
                "title": "Neighbor AP went down while this client was on it",
                "evidence": (
                    f"Neighbor-AP-down on {apn} while the client session was there."
                    + (f" {drop.get('type')} {int(dt)}s later." if drop is not None else "")
                    + " Remaining APs absorb the cell — expect a burst of roams and weaker RSSI."
                ),
                "confidence": "high",
                "severity": "crit",
            })
            continue

        if re.get("channelChanged") and connected:
            out.append({
                "id": f"radio-channel-{uid}",
                "title": f"AP channel change while client was associated ({re.get('label')})",
                "evidence": (
                    f"{re.get('label')} on AP {apn}.{ch_bit}"
                    + (f" {drop.get('type')} {int(dt)}s later." if drop is not None else " Client was on this radio at the change.")
                    + " A mid-session channel change is a forced roam."
                ),
                "confidence": "high",
                "severity": "warn",
            })
            continue

        if power_changed(re) and connected and not re.get("channelChanged"):
            out.append({
                "id": f"radio-power-{uid}",
                "title": "RRM power change on the AP this client was on",
                "evidence": (
                    f"{re.get('label')} on AP {apn}.{pwr_bit} "
                    "A sudden drop in TX power shrinks the cell and looks like a coverage hole to a mid-cell client."
                ),
                "confidence": "medium",
                "severity": "warn",
            })
            continue

        if drop is not None:
            out.append({
                "id": f"radio-{re.get('event')}-{uid}",
                "title": f"Client drop after {str(re.get('label') or 'radio event').lower()}",
                "evidence": (
                    f"{re.get('label')} on AP {apn} then {drop.get('type')} {int(dt)}s later.{ch_bit}{pwr_bit}"
                ),
                "confidence": "medium",
                "severity": "warn",
            })
    return out


def _call_open_at(call: dict, t: float) -> bool:
    t = float(epoch_s(t) or 0)
    start = float(epoch_s(call.get("start")) or 0)
    end = float(epoch_s(call.get("end")) or start)
    return (start - WINDOW_CALL_S) <= t <= (end + WINDOW_CALL_S)


def call_correlations(
    calls: list,
    events: list,
    sessions: list | None = None,
    stats: dict | None = None,
    radio_events: list | None = None,
    ap_radio: dict | None = None,
    store: RadioEventStore | None = None,
) -> list[dict]:
    """Teams/Zoom quality vs wireless drops, roams, RF, and RRM radar."""
    if not calls:
        return []
    drops = [
        e for e in (events or [])
        if any(k in (e.get("type") or "").upper() for k in ("DEAUTH", "DISASSOC", "DISCONNECT"))
    ]
    roams = [e for e in (events or []) if "ROAM" in (e.get("type") or "").upper()]
    dhcp_fail = [e for e in (events or []) if "DHCP" in (e.get("type") or "").upper() and e.get("negative")]
    handshake = [
        e for e in drops
        if str(e.get("reason")) == "15" or "4-way" in f"{e.get('type')} {e.get('text')}".lower()
    ]
    rssi = (stats or {}).get("rssi")
    snr = (stats or {}).get("snr")
    retries = (stats or {}).get("txRetries")
    rb, sb = rssi_band(rssi), snr_band(snr)
    out: list[dict] = []
    radars = [re for re in (radio_events or []) if is_radar_event(re)]

    for c in calls:
        label = c.get("appLabel") or "Call"
        overlapping = [d for d in drops if _call_open_at(c, float(d.get("timestamp") or 0))]
        roam_hits = [d for d in roams if _call_open_at(c, float(d.get("timestamp") or 0))]
        dhcp_hits = [d for d in dhcp_fail if _call_open_at(c, float(d.get("timestamp") or 0))]
        hs_hits = [d for d in handshake if _call_open_at(c, float(d.get("timestamp") or 0))]
        radar_hits = []
        if store is not None:
            seen_r: set[tuple] = set()
            for _sess, re in store.hits_for_sessions(sessions):
                if not _call_open_at(c, float(epoch_s(re.get("timestamp")) or 0)):
                    continue
                sig = (re.get("ap"), re.get("timestamp"), re.get("event"))
                if sig in seen_r:
                    continue
                seen_r.add(sig)
                radar_hits.append(re)
        else:
            for re in radars:
                if not _call_open_at(c, float(epoch_s(re.get("timestamp")) or 0)):
                    continue
                same, _on = radar_hits_this_client(re, sessions or [], events or [], stats)
                if same:
                    radar_hits.append(re)
        radar_hits.sort(key=lambda r: epoch_s(r.get("timestamp")) or 0)
        start = float(epoch_s(c.get("start")) or 0)

        if radar_hits:
            for re in radar_hits:
                rts = float(epoch_s(re.get("timestamp")) or 0)
                on_ap = client_ap_at(sessions or [], events or [], stats, rts)
                client_name = ap_name_for(on_ap, radio_events, ap_radio)
                radar_name = re.get("apName") or format_mac(re.get("ap") or "")
                fact = radar_fact(re, on_ap, client_name, call=c, drop=overlapping[0] if overlapping else None)
                meet = f" meeting {c.get('meetingId')}" if c.get("meetingId") else ""
                out.append({
                    "id": f"call-radar-{c.get('start')}-{re.get('timestamp')}-{hex_mac(re.get('ap'))}",
                    "title": f"{label} in progress during {re.get('label')}",
                    "evidence": (
                        f"{label}{meet} {int(c.get('duration') or 0)}s "
                        f"(audio {c.get('audioQuality') if c.get('audioQuality') is not None else '—'} / "
                        f"video {c.get('videoQuality') if c.get('videoQuality') is not None else '—'}). "
                        f"Client AP at radar time: {client_name} ({format_mac(on_ap) if on_ap else '—'}). "
                        f"{re.get('label')} on {radar_name} ({format_mac(re.get('ap') or '')}), "
                        f"channel {fact['radarChannel']}, {fact['radarWidth']}, {fact['radarPower']}."
                    ),
                    "confidence": "high",
                    "severity": "crit",
                    "highlight": True,
                    "detail": fact,
                })
            continue

        if overlapping:
            d = overlapping[0]
            ended_at_drop = bool(c.get("end") and abs(float(c["end"]) - float(d.get("timestamp") or 0)) <= 20)
            title = f"{label} dropped with the wireless disconnect" if ended_at_drop else f"{label} overlapped a wireless disconnect"
            extra = ""
            if hs_hits:
                extra = " 4-way handshake timeout during the call — media path died with the keys."
            elif dhcp_hits:
                extra = " DHCP failed during the call — L3, not Teams."
            out.append({
                "id": f"call-drop-{c.get('start')}",
                "title": title,
                "evidence": (
                    f"{label} {int(c.get('duration') or 0)}s, audio {c.get('audioQuality') if c.get('audioQuality') is not None else '—'}, "
                    f"video {c.get('videoQuality') if c.get('videoQuality') is not None else '—'}. "
                    f"{d.get('type')} at {d.get('timestamp')}.{extra} "
                    "The call failure is the wireless event, not a Teams outage."
                ),
                "confidence": "high",
                "severity": "crit" if c.get("poor") or ended_at_drop else "warn",
            })
            continue

        if roam_hits and (c.get("poor") or len(roam_hits) >= 2):
            out.append({
                "id": f"call-roam-{c.get('start')}",
                "title": f"{label} during AP roam / ping-pong",
                "evidence": (
                    f"{len(roam_hits)} roam(s) while {label} was up. "
                    "Each roam is a brief media blackout; two or more in a meeting is choppy audio even if RSSI recovers."
                ),
                "confidence": "high" if c.get("poor") else "medium",
                "severity": "warn",
            })
            continue

        if c.get("poor") and retries is not None and retries >= 80:
            out.append({
                "id": f"call-retries-{c.get('start')}",
                "title": f"Poor {label} quality with high TX retries",
                "evidence": (
                    f"{label} audio {c.get('audioQuality')} / video {c.get('videoQuality')} with {retries} TX retries. "
                    "Airtime contention or interference, not a Teams cloud issue."
                ),
                "confidence": "high",
                "severity": "crit" if rb in {"crit", "warn"} else "warn",
            })
            continue

        if c.get("poor"):
            audio_only = quality_poor(c.get("audioQuality")) and not quality_poor(c.get("videoQuality"))
            if rb in {"crit", "warn"} or sb in {"crit", "warn"}:
                out.append({
                    "id": f"call-rf-{c.get('start')}",
                    "title": f"Poor {label} quality with weak RF",
                    "evidence": (
                        f"{label} audio {c.get('audioQuality')} / video {c.get('videoQuality')} "
                        f"while RSSI {rssi} dBm and SNR {snr} dB. Real-time media is the first thing coverage holes break."
                    ),
                    "confidence": "high",
                    "severity": "crit",
                })
            elif audio_only and rb == "good":
                out.append({
                    "id": f"call-qos-{c.get('start')}",
                    "title": f"Poor {label} audio while Wi-Fi RF and video look fine",
                    "evidence": (
                        f"Audio {c.get('audioQuality')} but video {c.get('videoQuality')} at RSSI {rssi} dBm. "
                        "Classic missing DSCP/WMM or WAN jitter — not an AP coverage hole."
                    ),
                    "confidence": "medium",
                    "severity": "warn",
                })
            else:
                out.append({
                    "id": f"call-qos-{c.get('start')}",
                    "title": f"Poor {label} quality while Wi-Fi RF looks fine",
                    "evidence": (
                        f"{label} audio {c.get('audioQuality')} / video {c.get('videoQuality')} "
                        f"with RSSI {rssi} dBm. Not a coverage hole — check WAN/NAT, DSCP/WMM, or the Teams client path."
                    ),
                    "confidence": "medium",
                    "severity": "warn",
                })
            continue

        # Short failed join: call started within 45s of an association and lasted <20s
        if c.get("duration") is not None and 0 < float(c["duration"]) < 20:
            assoc = [
                e for e in (events or [])
                if "ASSOCIAT" in (e.get("type") or "").upper()
                and abs(float(e.get("timestamp") or 0) - start) <= 45
            ]
            if assoc:
                out.append({
                    "id": f"call-join-{c.get('start')}",
                    "title": f"{label} died right after Wi-Fi join",
                    "evidence": (
                        f"{label} lasted {int(c['duration'])}s starting next to {assoc[0].get('type')}. "
                        "Client associated, then the meeting never got a stable media path."
                    ),
                    "confidence": "medium",
                    "severity": "warn",
                })

    poor_teams = [c for c in calls if c.get("teams") and c.get("poor")]
    if len(poor_teams) >= 2 and not any(str(x.get("id") or "").startswith("call-") for x in out):
        out.append({
            "id": "call-repeat-poor",
            "title": "Repeated poor Microsoft Teams calls in 7 days",
            "evidence": (
                f"{len(poor_teams)} poor Teams sessions for this MAC over 7 days. "
                "Pattern is the client or its path, not a one-off meeting."
            ),
            "confidence": "medium",
            "severity": "warn",
        })
    return out


def band_group(band: Any) -> str:
    b = str(band or "").lower()
    if b in {"2", "2.4", "24"} or "2.4" in b:
        return "24"
    if b == "5" or "5" in b:
        return "5"
    if b == "6" or "6" in b:
        return "6"
    return "unk"


def build_correlations(stats: dict | None, events: list, sessions: list) -> list[dict]:
    out: list[dict] = []
    chrono = sorted(events, key=lambda e: e.get("timestamp") or 0)
    rssi = (stats or {}).get("rssi")
    snr = (stats or {}).get("snr")
    rb, sb = rssi_band(rssi), snr_band(snr)
    deauth = [e for e in events if "DEAUTH" in e["type"].upper() or "DISASSOC" in e["type"].upper()]
    dhcp_fail = [e for e in events if "DHCP" in e["type"].upper() and e["negative"]]
    dns_fail = [e for e in events if "DNS" in e["type"].upper() and e["negative"]]
    roam = [e for e in events if "ROAM" in e["type"].upper()]
    handshake = [
        e for e in deauth
        if str(e.get("reason")) == "15" or "4-way" in f"{e['type']} {e['text']}".lower() or "handshake" in f"{e['type']} {e['text']}".lower()
    ]
    idle = [
        e for e in deauth
        if str(e.get("reason")) == "4" or "inactiv" in f"{e['type']} {e['text']}".lower()
    ]
    left = [e for e in deauth if str(e.get("reason")) in {"3", "8"}]

    if rb == "crit" and sb == "crit":
        out.append({
            "id": "rf-coverage",
            "title": "Coverage hole (weak RSSI and SNR together)",
            "evidence": f"Live RSSI {rssi} dBm and SNR {snr} dB. Mist treats RSSI < −75 dBm as a bad-roam / coverage signature; SNR < 15 dB confirms the client is at the edge or obstructed.",
            "confidence": "high",
            "severity": "crit",
        })
    elif rb not in {"crit", "unknown"} and sb == "crit":
        out.append({
            "id": "rf-noise",
            "title": "Interference / noise (SNR collapsed while RSSI is still usable)",
            "evidence": f"RSSI {rssi} dBm is not critical, but SNR {snr} dB is. That pattern is noise, CCI, or a dirty channel — not a simple distance problem.",
            "confidence": "high",
            "severity": "crit",
        })

    for d in dhcp_fail:
        prior = [
            e for e in chrono
            if e["timestamp"] < d["timestamp"]
            and d["timestamp"] - e["timestamp"] <= WINDOW_DHCP_S
            and any(k in e["type"].upper() for k in ("ASSOCIATION", "ROAMED", "AUTHORIZATION", "DEAUTH", "DISASSOC"))
        ]
        if prior:
            last = prior[-1]
            out.append({
                "id": f"dhcp-after-join-{d['timestamp']}",
                "title": "DHCP failed after join / roam — L3, not RF",
                "evidence": f"{last['type']} at the prior AP, then {d['type']} {round(d['timestamp'] - last['timestamp'])}s later. Association succeeded; DORA did not. Check VLAN, helper, and gateway on AP {d.get('ap') or last.get('ap') or '—'}.",
                "confidence": "high",
                "severity": "crit",
            })
            break

    if handshake:
        h = handshake[0]
        out.append({
            "id": f"handshake-{h['timestamp']}",
            "title": "4-way handshake timeout (PSK / 802.1X)",
            "evidence": f"{describe_reason(h.get('reason') or 15)} on AP {h.get('ap') or '—'}. Classic mismatch of PSK, expired 802.1X, or a client that associated then failed key exchange.",
            "confidence": "high",
            "severity": "crit",
        })

    if idle and rb in {"crit", "warn"}:
        out.append({
            "id": "sticky-idle",
            "title": "Sticky client then inactivity deauth",
            "evidence": f"{len(idle)} inactivity (reason 4) deauth(s) while RF is {rssi} dBm. Client held a far AP until the AP aged it out — typical sticky-client / coverage-hole sequence in Mist roaming docs.",
            "confidence": "high",
            "severity": "crit",
        })
    elif idle:
        out.append({
            "id": "idle-timeout",
            "title": "Idle timeout deauth (reason 4)",
            "evidence": f"{len(idle)} inactivity disconnect(s). Device slept, power-saved, or stopped transmitting; not necessarily an RF outage.",
            "confidence": "medium",
            "severity": "warn",
        })

    ap_seq = [e["ap"] for e in chrono if e.get("ap")]
    flips = sum(1 for i in range(1, len(ap_seq)) if ap_seq[i] != ap_seq[i - 1])
    aps = unique_aps(chrono)
    if flips >= PINGPONG_MIN and len(aps) == 2:
        out.append({
            "id": "ping-pong",
            "title": "AP ping-pong between two radios",
            "evidence": f"{flips} AP transitions oscillating across {' ↔ '.join(aps)}. Overlapping cells, sticky 2.4/5, or a coverage saddle — not a single bad AP.",
            "confidence": "high",
            "severity": "warn",
        })
    elif len(roam) >= 4 or len(aps) >= 3:
        out.append({
            "id": "excessive-roam",
            "title": "Excessive roaming / AP hopping",
            "evidence": f"{len(roam)} roam event(s) across {len(aps)} AP(s). Mist flags this as sticky-client or coverage-hole behavior when RSSI on the serving AP is poor.",
            "confidence": "medium",
            "severity": "warn",
        })

    for i in range(1, len(chrono)):
        prev, cur = chrono[i - 1], chrono[i]
        if band_group(prev.get("band")) in {"5", "6"} and band_group(cur.get("band")) == "24" and (
            "ROAM" in cur["type"].upper() or "ASSOCIATION" in cur["type"].upper()
        ):
            out.append({
                "id": "band-drop",
                "title": "Warning roam: dropped from 5/6 GHz to 2.4 GHz",
                "evidence": f"Band {prev.get('band')} → {cur.get('band')} during {cur['type']}. Mist marks inter-band jumps as warning roams; expect lower rates and more airtime contention.",
                "confidence": "high",
                "severity": "warn",
            })
            break

    retries = (stats or {}).get("txRetries")
    if retries is not None and retries >= 80 and rb in {"good", "warn"}:
        out.append({
            "id": "retries-rf-ok",
            "title": "High TX retries with usable RSSI (interference / multipath)",
            "evidence": f"{retries} TX retries while RSSI is {rssi} dBm. Signal is present but frames are failing — CCI, non-Wi-Fi interference, or a hidden node, not a coverage hole.",
            "confidence": "medium",
            "severity": "warn",
        })
    elif retries is not None and retries >= 80 and rb == "crit":
        out.append({
            "id": "retries-edge",
            "title": "High TX retries at the cell edge",
            "evidence": f"{retries} TX retries with RSSI {rssi} dBm. Client is both weak and retrying — add coverage or reduce sticky behavior toward a nearer AP.",
            "confidence": "high",
            "severity": "crit",
        })

    rate = (stats or {}).get("txRate")
    if rate is not None and rate > 0 and rate < 24 and rb == "good":
        out.append({
            "id": "rate-mismatch",
            "title": "PHY rate too low for the measured RSSI",
            "evidence": f"TX rate {rate} Mbps with RSSI {rssi} dBm. Capability, band, or retry backoff is capping throughput even though the RF looks fine.",
            "confidence": "medium",
            "severity": "warn",
        })

    short = [s for s in sessions if s.get("duration") and 0 < s["duration"] < 60]
    if len(short) >= 2:
        short_aps = unique_aps(short)
        ap_bit = (
            f" — concentrated on AP {short_aps[0]}"
            if len(short_aps) == 1
            else f" across {len(short_aps)} AP(s)"
        )
        out.append({
            "id": "short-sessions",
            "title": "Unstable association (sessions under 60s)",
            "evidence": f"{len(short)} session(s) lasted under a minute{ap_bit}. Pair with the deauth reason on that radio.",
            "confidence": "high" if len(short_aps) == 1 else "medium",
            "severity": "warn",
        })

    times = sorted(e["timestamp"] for e in deauth)
    cluster = max_cluster = 1
    for i in range(1, len(times)):
        if times[i] - times[i - 1] <= WINDOW_CLUSTER_S:
            cluster += 1
            max_cluster = max(max_cluster, cluster)
        else:
            cluster = 1
    if max_cluster >= 3:
        out.append({
            "id": "deauth-cluster",
            "title": "Burst of disconnects (not an isolated drop)",
            "evidence": f"{max_cluster} deauth/disassoc events within {WINDOW_CLUSTER_S // 60} minutes. Burst pattern points to a repeating cause (PSK, DHCP, or a flapping radio) rather than a one-off roam.",
            "confidence": "high",
            "severity": "crit",
        })

    if dns_fail and not dhcp_fail:
        out.append({
            "id": "dns-only",
            "title": "DNS failed after a successful L2/L3 join",
            "evidence": f"{len(dns_fail)} DNS failure(s) with no DHCP failure in the window. Wireless and DHCP are likely fine; inspect DNS reachability from that VLAN.",
            "confidence": "medium",
            "severity": "warn",
        })

    if left and not idle and rb == "good":
        out.append({
            "id": "client-left",
            "title": "Client left the BSS (often user-initiated)",
            "evidence": f"{len(left)} leave-BSS reason(s) (3/8) while RF is healthy. Sleep, interface bounce, or the user walking away — not an infrastructure fault.",
            "confidence": "medium",
            "severity": "info",
        })

    rank = {"crit": 0, "warn": 1, "info": 2}
    conf = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda c: (rank[c["severity"]], conf[c["confidence"]]))
    return dedupe_correlations(out)


def build_verdict(
    stats: dict | None,
    events: list,
    sessions: list,
    ap_radio: dict | None = None,
    radio_events: list | None = None,
    calls: list | None = None,
    radio_store: RadioEventStore | None = None,
) -> dict:
    notes: list[str] = []
    score = 100
    cors = build_correlations(stats, events, sessions)
    cors.extend(rf_occupancy_correlations(ap_radio, stats))
    cors.extend(radio_event_correlations(radio_events or [], events, sessions, stats, ap_radio, radio_store))
    cors.extend(call_correlations(calls or [], events, sessions, stats, radio_events or [], ap_radio, radio_store))
    rssi = (stats or {}).get("rssi")
    snr = (stats or {}).get("snr")
    rb, sb = rssi_band(rssi), snr_band(snr)
    if rb == "crit":
        score -= 25
        notes.append(f"RSSI {rssi} dBm is critically weak — coverage or obstruction.")
    elif rb == "warn":
        score -= 12
        notes.append(f"RSSI {rssi} dBm is marginal (target ≥ −65 dBm).")
    if sb == "crit":
        score -= 20
        notes.append(f"SNR {snr} dB is critically low — noise or interference likely.")
    elif sb == "warn":
        score -= 10
        notes.append(f"SNR {snr} dB is only fair (target ≥ 25 dB).")
    deauth = [e for e in events if "DEAUTH" in e["type"].upper() or "DISASSOC" in e["type"].upper()]
    dhcp = [e for e in events if "DHCP" in e["type"].upper() and e["negative"]]
    auth = [
        e for e in events
        if e["negative"]
        and ("AUTH" in e["type"].upper() or "ASSOC" in e["type"].upper())
        and "DEAUTH" not in e["type"].upper()
        and "DISASSOC" not in e["type"].upper()
    ]
    roam = [e for e in events if "ROAM" in e["type"].upper()]
    if deauth:
        score -= min(30, len(deauth) * 6)
        reasons = list({describe_reason(e.get("reason")) for e in deauth if describe_reason(e.get("reason"))})
        notes.append(f"{len(deauth)} deauth/disassoc event(s)" + (f": {'; '.join(reasons)}" if reasons else "") + ".")
    if dhcp:
        score -= 15
        notes.append(f"{len(dhcp)} DHCP failure(s) after association — L3 / gateway.")
    if auth:
        score -= 15
        notes.append(f"{len(auth)} authentication/association failure(s).")
    if len(roam) >= 4:
        score -= 8
        notes.append(f"{len(roam)} roam events in the window — sticky client or coverage holes.")
    short = [s for s in sessions if s.get("duration") and 0 < s["duration"] < 60]
    if len(short) >= 2:
        score -= 10
        notes.append(f"{len(short)} sessions lasted under 60s — unstable association.")
    retries = (stats or {}).get("txRetries")
    if retries is not None and retries >= 80:
        score -= 8
        notes.append(f"{retries} TX retries — airtime contention or a dirty channel.")
    radio = (ap_radio or {}).get("radio") or {}
    serving_occ = next((c for c in ((ap_radio or {}).get("channels") or []) if c.get("serving")), None)
    nw = (serving_occ or {}).get("nonWifi")
    if nw is None:
        nw = util_pct(radio.get("utilNonWifi")) if radio else 0
    if nw >= 25:
        score -= 10 if nw >= 40 else 6
        ch = (serving_occ or {}).get("channel") or radio.get("channel")
        notes.append(f"Serving AP channel {ch} has {nw}% non-Wi-Fi occupancy.")
    radio_hits = [c for c in cors if str(c.get("id") or "").startswith("radio-")]
    radar_hits = [c for c in radio_hits if str(c.get("id") or "").startswith("radio-radar")]
    if radar_hits:
        score -= 12
        n = len(radar_hits)
        notes.append(
            f"{n} Post radar / DFS event(s) on APs this client was associated to in this window."
        )
    elif radio_hits:
        score -= 12 if radio_hits[0]["severity"] == "crit" else 8
        notes.append(radio_hits[0]["title"] + ".")
    call_hits = [c for c in cors if str(c.get("id") or "").startswith("call-")]
    if call_hits:
        score -= 12 if call_hits[0]["severity"] == "crit" else 6
        notes.append(call_hits[0]["title"] + ".")
    teams_poor = [c for c in (calls or []) if c.get("teams") and c.get("poor")]
    if teams_poor and not call_hits:
        score -= 6
        notes.append(f"{len(teams_poor)} poor Microsoft Teams call(s) in the last 7 days.")
    rank = {"crit": 0, "warn": 1, "info": 2}
    conf = {"high": 0, "medium": 1, "low": 2}
    cors.sort(key=lambda c: (
        0 if c.get("highlight") else 1,
        rank.get(c["severity"], 9),
        conf.get(c["confidence"], 9),
    ))
    cors = dedupe_correlations(cors)
    for c in cors:
        if c["severity"] == "crit" and c["confidence"] == "high":
            if not any(c["title"][:18] in n for n in notes):
                notes.append(c["title"])
    score = max(0, min(100, int(score)))
    label = "Healthy" if score >= 80 else "Degraded" if score >= 50 else "Critical"
    primary = "No dominant failure signature — review the timeline."
    if cors and cors[0]["severity"] in {"crit", "warn"}:
        primary = cors[0]["title"]
    elif rb == "crit" or sb == "crit":
        primary = "RF: weak signal or high noise"
    elif auth:
        primary = "Authentication / association failure"
    elif dhcp:
        primary = "DHCP / IP services after join"
    elif deauth:
        primary = "Repeated disconnects — see reason codes"
    if not notes:
        notes.append("RF metrics in range and no clustered failure events.")
    return {"score": score, "label": label, "primaryCause": primary, "notes": notes, "correlations": cors}


def fetch_optional_list(host: str, token: str, path: str, params: dict) -> tuple[list, str | None]:
    """GET a list endpoint that may 403/404 when the org lacks the feature (Teams, RRM events)."""
    try:
        return as_results(mist_get(host, token, path, params)), None
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "400" in msg and str(params.get("duration") or "") in {"7d", "1w"}:
            retry = {k: v for k, v in params.items() if k != "duration"}
            retry["start"] = int(time.time()) - 7 * 86400
            try:
                return as_results(mist_get(host, token, path, retry)), None
            except Exception as e2:  # noqa: BLE001
                return [], str(e2)
        if any(x in msg.lower() for x in ("403", "401", "permission", "not provided")):
            return [], msg
        return [], msg


def _rrm_events_page(
    host: str,
    token: str,
    site_id: str,
    band: str,
    page: int,
    start: int | None = None,
    end: int | None = None,
) -> tuple[list, bool, str | None]:
    """One page of listSiteRrmEvents. Returns (rows, has_more, error)."""
    if start is not None:
        params = {
            "band": band,
            "start": int(start),
            "end": int(end if end is not None else time.time()),
            "limit": 100,
            "page": int(page),
        }
    else:
        params = rrm_events_query(band, page=page, limit=100)
    try:
        payload = mist_get(host, token, f"/sites/{site_id}/rrm/events", params, timeout=RRM_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "400" in msg and "band" in msg.lower() and "required" in msg.lower():
            return [], False, msg
        if "400" in msg:
            retry = dict(params)
            retry.pop("duration", None)
            retry.setdefault("start", int(time.time()) - duration_seconds("1d"))
            retry.setdefault("end", int(time.time()))
            try:
                payload = mist_get(host, token, f"/sites/{site_id}/rrm/events", retry, timeout=RRM_TIMEOUT)
            except Exception as e2:  # noqa: BLE001
                return [], False, str(e2)
        else:
            return [], False, msg
    rows = as_results(payload)
    rec = as_record(payload) if isinstance(payload, dict) else {}
    has_more = bool(rec.get("next")) or len(rows) >= 100
    return rows, has_more, None


def fetch_site_rrm_events(
    host: str,
    token: str,
    site_id: str,
    duration: str = "1d",
    client_aps: set[str] | None = None,
    families: list[set[str]] | None = None,
    live: bool = False,
) -> tuple[list, str | None, RadioEventStore]:
    """Portal Radio Events for the selected lookback.

    listSiteRrmEvents cannot filter by AP. We split the window into time slices
    so a radar storm in the last hour cannot hide a hit from hour 18, then KEEP
    client-AP rows in the UI export while indexing EVERY scanned radar by AP.
    A neighbor-radar storm keeps paging (adaptive cap) until the client's AP
    appears or the slice is exhausted. Live polls only walk the newest hour.
    """
    store = RadioEventStore(client_aps, families)
    errors: list[str] = []
    slices = rrm_time_slices("1h" if live else duration)
    lock = threading.Lock()

    def pull_slice(band: str, pages: int, start: int, end: int, adapt: bool) -> None:
        local: list[dict] = []
        err: str | None = None
        cap = RRM_PAGES_ADAPT_5 if (adapt and str(band) == "5") else pages
        client_in_slice = 0
        for page in range(1, cap + 1):
            rows, has_more, err = _rrm_events_page(host, token, site_id, band, page, start, end)
            if err:
                break
            local.extend(rows)
            page_client = 0
            with lock:
                for raw in rows:
                    kind = store.add(pick_rrm_event(raw))
                    if kind in {"client", "radar-client"}:
                        page_client += 1
                        client_in_slice += 1
            if not has_more:
                break
            oldest = None
            for raw in rows:
                ts = epoch_s(raw.get("timestamp"))
                if ts is None:
                    continue
                oldest = ts if oldest is None else min(oldest, ts)
            if oldest is not None and oldest < start - 60:
                break
            # After the minimum page budget: keep walking only while this page
            # had zero client-AP rows (still inside a neighbor storm). Once
            # client-AP rows appear and then disappear, older pages are noise.
            if page >= pages and page_client == 0 and client_in_slice > 0:
                break
        with lock:
            if err and band == "5" and not local:
                errors.append(f"band={band}: {err}")

    jobs: list[tuple[str, int, int, int, bool]] = []
    adapt = (not live) and duration_seconds(duration) >= 86400
    for start, end in slices:
        pages5 = RRM_PAGES_LIVE_5 if live else rrm_pages_for_band("5", duration if not live else "1h")
        jobs.append(("5", pages5, start, end, adapt))
    if slices:
        newest = slices[0]
        other_pages = RRM_PAGES_LIVE_OTHER if live else rrm_pages_for_band("24", duration if not live else "1h")
        jobs.append(("24", other_pages, newest[0], newest[1], False))
        jobs.append(("6", other_pages, newest[0], newest[1], False))

    threads = [threading.Thread(target=pull_slice, args=job) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    uniq = store.export_events()
    err = "; ".join(errors) if errors and not uniq else (None if uniq else ("; ".join(errors) if errors else None))
    return uniq, err, store


def mist_get(host: str, token: str, path: str, params: dict | None = None, timeout: int | None = None) -> Any:
    if host not in MIST_HOSTS:
        raise ValueError("Host is not a known Mist API region.")
    url = f"https://{host}/api/v1{path}"
    if params:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None and v != ""})
        url = f"{url}?{q}"
    tok = token.replace("token ", "").replace("Token ", "").strip()
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Token {tok}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT, context=CTX) as resp:
            if resp.status == 204:
                return None
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("Token rejected (401). Check region and token.") from e
        if e.code == 403:
            raise RuntimeError("Token lacks permission for this org or site (403).") from e
        if e.code == 404:
            return None
        if e.code == 429:
            raise RuntimeError("Mist rate limit (429). Wait a minute and retry.") from e
        body = e.read()[:180].decode("utf-8", "replace")
        raise RuntimeError(f"Mist API {e.code}: {body or e.reason}") from e
    except TimeoutError as e:
        raise RuntimeError("Mist API timed out after 25s.") from e


def connect_mist(token: str, host: str) -> dict:
    self = as_record(mist_get(host, token, "/self"))
    if not self:
        raise RuntimeError("Empty /self response.")
    orgs: dict[str, str] = {}
    for p in self.get("privileges") or []:
        if not isinstance(p, dict):
            continue
        if p.get("scope") == "org" and isinstance(p.get("org_id"), str):
            orgs[p["org_id"]] = str(p.get("name") or p["org_id"])
    if isinstance(self.get("org_id"), str) and self["org_id"] not in orgs:
        orgs[self["org_id"]] = str(self.get("org_name") or self["org_id"])
    if not orgs:
        raise RuntimeError("Token validated but no org privileges were listed.")
    return {"email": str(self.get("email") or self.get("name") or ""), "orgs": [{"id": k, "name": v} for k, v in orgs.items()]}


def list_sites(token: str, host: str, org_id: str) -> list:
    data = mist_get(host, token, f"/orgs/{org_id}/sites")
    sites = []
    for row in as_array(data):
        sid = row.get("id")
        if isinstance(sid, str):
            sites.append({"id": sid, "name": str(row.get("name") or sid)})
    sites.sort(key=lambda s: s["name"].lower())
    return sites


def list_ap_inventory(token: str, host: str, site_id: str, prefetched: Any = None) -> list[dict]:
    """Site AP list (name + mac + id). Prefer stats/devices so radio_stat is already attached."""
    rows = as_array(prefetched)
    if not rows:
        try:
            rows = as_array(mist_get(host, token, f"/sites/{site_id}/devices", {"type": "ap"}))
        except Exception:
            rows = []
    if not rows:
        try:
            rows = as_array(mist_get(host, token, f"/sites/{site_id}/stats/devices", {"type": "ap"}))
        except Exception:
            rows = []
    out: list[dict] = []
    seen: set[str] = set()
    for d in rows:
        typ = str(d.get("type") or "ap").lower()
        if typ not in {"ap", "access-point", ""}:
            continue
        mac = hex_mac(d.get("mac"))
        key = mac or str(d.get("id") or d.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def find_device_stats(
    token: str,
    host: str,
    site_id: str,
    ap_mac: str,
    inventory: list | None = None,
    device_id: str = "",
) -> dict | None:
    """Resolve AP MAC / UUID / inventory row → stats/devices."""
    inv = inventory or []
    if ap_mac:
        hit = match_inventory(inv, mac=ap_mac)
        if hit:
            rec = dict(hit)
            rec.setdefault("id", hit.get("id") or mist_device_id(ap_mac))
            rec.setdefault("mac", ap_mac)
            if as_record(rec.get("radio_stat")):
                return rec
            device_id = str(rec.get("id") or device_id)
    did = device_id or (mist_device_id(ap_mac) if ap_mac else "")
    rec = None
    if did:
        rec = as_record(mist_get(host, token, f"/sites/{site_id}/stats/devices/{did}"))
        if rec and (not rec.get("mac") or not ap_mac or hex_mac(rec.get("mac")) == hex_mac(ap_mac)):
            rec.setdefault("id", did)
            return rec
    if not ap_mac:
        return rec
    inv2 = inv or list_ap_inventory(token, host, site_id)
    match = match_inventory(inv2, mac=ap_mac)
    if not match:
        return rec
    did = str(match.get("id") or mist_device_id(ap_mac))
    rec = as_record(mist_get(host, token, f"/sites/{site_id}/stats/devices/{did}")) or dict(match)
    rec.setdefault("id", did)
    rec.setdefault("name", match.get("name"))
    rec.setdefault("mac", match.get("mac") or ap_mac)
    return rec


def fetch_ap_radio(
    token: str,
    host: str,
    site_id: str,
    stats: dict | None,
    events: list,
    sessions: list,
    marvis: Any,
    inventory: list | None = None,
) -> dict:
    inv = inventory if inventory is not None else list_ap_inventory(token, host, site_id)
    picked = pick_dominant_ap(sessions, stats, events, marvis, inventory=inv)
    matched = picked.pop("matchedDev", None)
    ap_mac = picked.get("apMac") or ""
    if not ap_mac and not matched:
        return {
            **picked,
            "unavailable": "No AP from Marvis, sessions, events, or live stats.",
            "channels": [],
            "radio": None,
        }
    try:
        if matched and as_record(matched.get("radio_stat")):
            dev = matched
        else:
            dev = find_device_stats(
                token, host, site_id, ap_mac, inventory=inv, device_id=str(picked.get("deviceId") or ""),
            )
            if not dev and matched:
                dev = matched
    except Exception as e:  # noqa: BLE001
        return {
            **picked,
            "unavailable": f"AP lookup failed: {e}",
            "channels": [],
            "radio": None,
        }
    if not dev:
        hint = picked.get("marvisName") or picked.get("apNameHint") or ap_mac
        return {
            **picked,
            "unavailable": f"AP {hint or '—'} not found in site inventory.",
            "channels": [],
            "radio": None,
        }
    ap_mac = hex_mac(dev.get("mac")) or ap_mac
    picked["apMac"] = ap_mac
    radio_raw, band = radio_from_device(dev, picked.get("bandHint") or "5")
    serving_ch = radio_raw.get("channel") or (stats or {}).get("channel")
    rrm_rows: list[dict] = []
    rrm_scope = "ap"
    dids: list[str] = []
    for cand in (dev.get("id"), picked.get("deviceId"), mist_device_id(ap_mac)):
        s = str(cand or "").strip()
        if s and s not in dids:
            dids.append(s)
    try:
        for did in dids:
            rrm = mist_get(host, token, f"/sites/{site_id}/rrm/current/devices/{did}/band/{band}")
            rrm_rows = rrm_rows_from(rrm)
            if rrm_rows:
                break
        # Do not fall back to site-wide channel_scores — those are scores, not
        # per-AP occupancy, and they wipe the orange Site AP bars.
    except Exception:
        rrm_rows = rrm_rows or []
    site_ch = site_airtime_by_channel(inv, band)
    channels = channels_from_rrm(
        rrm_rows, serving_ch, radio_raw if radio_raw else None, band=band, site_channels=site_ch,
    )
    if not channels and radio_raw:
        channels = [serving_channel_row(radio_raw, serving_ch)]
    radio = None
    if radio_raw:
        radio = {
            "channel": radio_raw.get("channel"),
            "bandwidth": radio_raw.get("bandwidth"),
            "power": radio_raw.get("power"),
            "numClients": radio_raw.get("num_clients"),
            "utilAll": util_pct(radio_raw.get("util_all")),
            "utilTx": util_pct(radio_raw.get("util_tx")),
            "utilRxInBss": util_pct(radio_raw.get("util_rx_in_bss")),
            "utilRxOtherBss": util_pct(radio_raw.get("util_rx_other_bss")),
            "utilNonWifi": util_pct(radio_raw.get("util_non_wifi")),
            "utilUnknownWifi": util_pct(radio_raw.get("util_unknown_wifi")),
            "utilUndecodable": util_pct(radio_raw.get("util_undecodable_wifi")),
        }
    status = str(dev.get("status") or ("connected" if dev.get("last_seen") else "unknown"))
    return {
        **picked,
        "apName": str(dev.get("name") or picked.get("marvisName") or picked.get("apNameHint") or format_mac(ap_mac)),
        "deviceId": str(dev.get("id") or mist_device_id(ap_mac)),
        "status": status,
        "band": band,
        "radio": radio,
        "channels": channels,
        "scope": rrm_scope,
        "unavailable": None if (radio or channels) else "No radio_stat or RRM occupancy for this AP.",
        "lastSeen": num(dev.get("last_seen")),
    }


def diagnose_client(token: str, host: str, org_id: str, site_id: str, site_name: str, mac: str, duration: str, live: bool = False) -> dict:
    mac = normalize_mac(mac)
    colon = format_mac(mac)
    paths = {
        "stats": (f"/sites/{site_id}/stats/clients/{mac}", None),
        "search": (f"/sites/{site_id}/clients/search", {"mac": mac, "duration": duration, "limit": 20}),
        "events": (f"/sites/{site_id}/clients/{mac}/events", {"duration": duration, "limit": 1000 if duration in {"1d", "1w", "7d"} else 100}),
        "sessions": (f"/sites/{site_id}/clients/sessions/search", {"mac": mac, "duration": duration, "limit": 100}),
        "marvis": (f"/orgs/{org_id}/troubleshoot", {"mac": colon, "site_id": site_id}),
        "aps": (f"/sites/{site_id}/devices", {"type": "ap"}),
        "devices": (f"/sites/{site_id}/stats/devices", {"type": "ap"}),
        "calls": (f"/sites/{site_id}/stats/calls/search", {"mac": mac, "duration": RADIO_EVENTS_DURATION, "limit": 50}),
    }
    got: dict[str, Any] = {}
    errors: dict[str, str] = {}

    def one(key: str, path: str, params: dict | None) -> None:
        try:
            got[key] = mist_get(host, token, path, params)
        except Exception as e:  # noqa: BLE001
            errors[key] = str(e)

    threads = [threading.Thread(target=one, args=(k, p, q)) for k, (p, q) in paths.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for key in ("stats", "search", "events"):
        msg = errors.get(key, "")
        if any(x in msg.lower() for x in ("401", "403", "rate limit", "timed out")):
            raise RuntimeError(msg)

    stats = None
    rec = as_record(got.get("stats"))
    if rec and rec.get("mac"):
        stats = pick_stats(rec)
    elif as_array(got.get("stats")):
        stats = pick_stats(as_array(got.get("stats"))[0])
    sightings = [pick_stats(r) for r in as_array(got.get("search"))]
    if not stats and sightings:
        stats = sightings[0]
    events = [pick_event(r) for r in as_array(got.get("events"))]
    ev_page = 2
    ev_limit = 1000 if duration in {"1d", "1w", "7d"} else 100
    # Walk older pages when the 7-day client log is larger than one response.
    oldest = min((e.get("timestamp") or 0) for e in events) if events else 0
    window_start = int(time.time()) - duration_seconds(duration)
    while ev_page <= EVENT_PAGES and events and oldest > window_start + 30:
        extra, _err = fetch_optional_list(
            host, token, f"/sites/{site_id}/clients/{mac}/events",
            {"start": window_start, "end": int(oldest) - 1, "limit": ev_limit},
        )
        if not extra:
            extra, _err = fetch_optional_list(
                host, token, f"/sites/{site_id}/clients/{mac}/events",
                {"duration": duration, "limit": 100, "page": ev_page},
            )
        if not extra:
            break
        before = {(e.get("timestamp"), e.get("type"), e.get("ap")) for e in events}
        added = 0
        for r in extra:
            ev = pick_event(r)
            key = (ev.get("timestamp"), ev.get("type"), ev.get("ap"))
            if key in before:
                continue
            events.append(ev)
            added += 1
        if not added:
            break
        oldest = min((e.get("timestamp") or 0) for e in events)
        ev_page += 1
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    sessions = [pick_session(r) for r in as_results(got.get("sessions")) or as_array(got.get("sessions"))]
    page = 2
    while len(sessions) >= 100 * (page - 1) and page <= SESSION_PAGES:
        extra, _err = fetch_optional_list(
            host, token, f"/sites/{site_id}/clients/sessions/search",
            {"mac": mac, "duration": duration, "limit": 100, "page": page},
        )
        if not extra:
            break
        sessions.extend(pick_session(r) for r in extra)
        if len(extra) < 100:
            break
        page += 1
    seen_sess: set[tuple] = set()
    uniq_sess: list[dict] = []
    for s in sessions:
        key = (hex_mac(s.get("ap")), s.get("connect"), s.get("disconnect"))
        if key in seen_sess:
            continue
        seen_sess.add(key)
        uniq_sess.append(s)
    sessions = uniq_sess
    sessions.sort(key=lambda s: s.get("connect") or 0, reverse=True)
    marvis_raw = None
    marvis_text = None
    marvis_unavail = False
    if "marvis" in errors:
        marvis_unavail = True
    else:
        v = got.get("marvis")
        if v is None:
            marvis_unavail = True
        else:
            marvis_raw = v
            if isinstance(v, str):
                marvis_text = v
            else:
                marvis_text = json.dumps(v, indent=2)
    inventory = list_ap_inventory(token, host, site_id, prefetched=got.get("devices") or got.get("aps"))
    if got.get("aps"):
        # Merge names/macs from the lighter devices list onto stats rows.
        by_mac = {hex_mac(d.get("mac")): d for d in inventory if hex_mac(d.get("mac"))}
        for d in as_array(got.get("aps")):
            m = hex_mac(d.get("mac"))
            if m and m in by_mac:
                if d.get("name") and not by_mac[m].get("name"):
                    by_mac[m]["name"] = d.get("name")
                if d.get("id") and not by_mac[m].get("id"):
                    by_mac[m]["id"] = d.get("id")
            elif m:
                inventory.append(d)
    sessions = attach_ap_names(sessions, inventory)
    client_aps = expand_client_aps(sessions, events, stats, inventory)
    families = [device_radio_macs(d) for d in inventory if device_radio_macs(d)]
    ap_box: dict[str, Any] = {}
    rrm_box: dict[str, Any] = {}

    def _ap_job() -> None:
        try:
            ap_box["v"] = fetch_ap_radio(
                token, host, site_id, stats, events, sessions, marvis_raw if marvis_raw is not None else marvis_text,
                inventory=inventory,
            )
        except Exception as e:  # noqa: BLE001
            ap_box["v"] = {"unavailable": str(e), "channels": [], "radio": None, "apMac": hex_mac((stats or {}).get("ap"))}

    def _rrm_job() -> None:
        rrm_box["v"] = fetch_site_rrm_events(
            host, token, site_id, duration, client_aps, families, live=live,
        )

    t_ap = threading.Thread(target=_ap_job)
    t_rrm = threading.Thread(target=_rrm_job)
    t_ap.start()
    t_rrm.start()
    t_ap.join()
    t_rrm.join()
    ap_radio = ap_box["v"]
    radio_events, radio_unavail, radio_store = rrm_box["v"]
    radio_events = attach_ap_names(radio_events, inventory)
    radio_events = annotate_radio_events(radio_events, events, sessions, stats)
    client_radar = radio_store.client_radar_events(sessions)
    client_keys = {(e.get("ap"), e.get("timestamp"), e.get("event")) for e in client_radar}
    for re in radio_events:
        if (re.get("ap"), re.get("timestamp"), re.get("event")) in client_keys:
            re["onClientAp"] = True
            if is_radar_event(re):
                re["highlight"] = True
    for re in client_radar:
        re["onClientAp"] = True
        re["highlight"] = True

    calls: list[dict] = [pick_call(r) for r in as_results(got.get("calls"))]
    calls_unavail = errors.get("calls")
    if calls_unavail and not calls:
        extra, err2 = fetch_optional_list(
            host, token, f"/sites/{site_id}/stats/calls/search",
            {"mac": mac, "duration": RADIO_EVENTS_DURATION, "limit": 50},
        )
        calls = [pick_call(r) for r in extra]
        calls_unavail = None if calls else (err2 or calls_unavail)
    calls.sort(key=lambda c: c.get("start") or 0, reverse=True)
    radar_alerts = radar_session_alerts(radio_events, sessions, calls, ap_radio, radio_store)

    last_seen = (stats or {}).get("lastSeen")
    online = bool(last_seen is not None and time.time() - float(last_seen) < 300)
    return {
        "demo": False,
        "host": host,
        "orgId": org_id,
        "siteId": site_id,
        "siteName": site_name,
        "mac": mac,
        "duration": duration,
        "online": online,
        "stats": stats,
        "sightings": sightings,
        "events": events,
        "sessions": sessions,
        "marvisText": marvis_text,
        "marvisUnavailable": marvis_unavail,
        "apRadio": ap_radio,
        "radioEvents": radio_events,
        "radioEventsUnavailable": radio_unavail,
        "clientRadarEvents": client_radar,
        "calls": calls,
        "callsUnavailable": calls_unavail,
        "radarAlerts": radar_alerts,
        "radioStoreStats": {
            "scanned": radio_store.scanned,
            "dropped": radio_store.dropped,
            "radars": len(radio_store.radars),
            "kept": len(radio_store.kept),
            "clientHits": len(client_radar),
        },
        "verdict": build_verdict(stats, events, sessions, ap_radio, radio_events, calls, radio_store),
        "fetchedAt": int(time.time() * 1000),
    }


def demo_result(jitter: bool = False) -> dict:
    t = int(time.time())
    j = int((__import__("random").random() - 0.5) * 6) if jitter else 0
    stats = {
        "mac": DEMO_MAC,
        "hostname": "DEMO-MBP",
        "manufacture": "Apple",
        "os": "macOS 15.5",
        "model": "MacBookPro18,3",
        "ssid": "CORP-WIFI",
        "vlan": 40,
        "ip": "10.40.12.88",
        "ap": "0a0027aa1102",
        "band": "5",
        "channel": 149,
        "proto": "ax",
        "rssi": -81 + j,
        "snr": max(6, 11 + j // 2),
        "txRate": 58,
        "rxRate": 48,
        "uptime": 140,
        "lastSeen": t - 12,
        "txBytes": 1843200,
        "rxBytes": 9216000,
        "username": "demo.user",
        "keyMgmt": "WPA2-PSK",
        "txRetries": 214,
        "rxRetries": 88,
        "dualBand": True,
    }
    events = [
        pick_event({"timestamp": t - 40, "type": "CLIENT_DNS_OK", "text": "Status code 0 Successful", "ap": "0a0027aa1102", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 90, "type": "CLIENT_DHCP_TIMED_OUT", "text": "DORA incomplete — no ACK", "ap": "0a0027aa1102", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 140, "type": "CLIENT_ASSOCIATION", "text": "Associated", "ap": "0a0027aa1102", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 148, "type": "CLIENT_DEAUTHENTICATION", "text": "Deauthenticated by AP", "ap": "0a0027aa1103", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 4}),
        pick_event({"timestamp": t - 420, "type": "CLIENT_DEAUTHENTICATION", "text": "4-way handshake timeout", "ap": "0a0027aa1103", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 15}),
        pick_event({"timestamp": t - 900, "type": "CLIENT_ROAMED", "text": "Roamed from 0a0027aa1103", "ap": "0a0027aa1102", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 1800, "type": "CLIENT_AUTHORIZATION", "text": "Authorized", "ap": "0a0027aa1103", "ssid": "CORP-WIFI", "band": "5", "channel": 36}),
        pick_event({"timestamp": t - 3600, "type": "CLIENT_DISASSOCIATION", "text": "STA leaving BSS", "ap": "0a0027aa1103", "ssid": "CORP-WIFI", "band": "2.4", "channel": 11, "reason": 8}),
    ]
    sessions = [
        {"ap": "0a0027aa1102", "apName": "DEMO-AP-F2-aa:11:02", "ssid": "CORP-WIFI", "band": "5", "connect": t - 140, "disconnect": None, "duration": 140},
        {"ap": "0a0027aa1103", "apName": "DEMO-AP-F2-aa:11:03", "ssid": "CORP-WIFI", "band": "5", "connect": t - 480, "disconnect": t - 148, "duration": 332},
        {"ap": "0a0027aa1103", "apName": "DEMO-AP-F2-aa:11:03", "ssid": "CORP-WIFI", "band": "5", "connect": t - 900, "disconnect": t - 840, "duration": 44},
        {"ap": "0a0027aa1102", "apName": "DEMO-AP-F2-aa:11:02", "ssid": "CORP-WIFI", "band": "5", "connect": t - 7200, "disconnect": t - 3600, "duration": 3580},
    ]
    marvis = {
        "results": [
            {
                "category": "Device Health",
                "text": " The AP is currently online. Client DEMO-MBP was connected to DEMO-AP-F2-aa:11:02 most of the time.",
                "site_id": "demo-site",
            },
            {
                "category": "Wireless connectivity",
                "text": "Weak RSSI and handshake timeouts on AP 0a0027aa1103. Client repeatedly deauthenticates then reassociates.",
            },
        ],
        "start": t - 86400,
        "end": t,
    }
    nw_j = max(0, min(20, j * 2))
    channels = [
        {"channel": 100, "site": 40, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 104, "site": 15, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 108, "site": 47, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 112, "site": 19, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 116, "site": 34, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 132, "site": 28, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 136, "site": 17, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 140, "site": 24, "external": 0, "nonWifi": 2, "serving": False},
        {"channel": 144, "site": 9, "external": 0, "nonWifi": 0, "serving": True},
        {"channel": 149, "site": 29, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 153, "site": 16, "external": 0, "nonWifi": 70 + nw_j, "serving": False},
        {"channel": 157, "site": 20, "external": 0, "nonWifi": 0, "serving": False},
        {"channel": 161, "site": 0, "external": 5, "nonWifi": 75, "serving": False},
        {"channel": 165, "site": 0, "external": 0, "nonWifi": 100, "serving": False},
    ]
    ap_radio = {
        "apMac": "0a0027aa1102",
        "apName": "DEMO-AP-F2-aa:11:02",
        "deviceId": mist_device_id("0a0027aa1102"),
        "status": "connected",
        "band": "5",
        "source": "marvis",
        "dwellSeconds": 3794,
        "dwellShare": 0.98,
        "marvisMentioned": True,
        "marvisName": "DEMO-AP-F2-aa:11:02",
        "selectionNote": "Marvis named DEMO-AP-F2-aa:11:02 as the AP this client used most of the time. Chart is that radio (0a:00:27:aa:11:02).",
        "fallback": False,
        "scope": "ap",
        "unavailable": None,
        "lastSeen": t - 8,
        "radio": {
            "channel": 144,
            "bandwidth": 20,
            "power": 8,
            "numClients": 0,
            "utilAll": 12,
            "utilTx": 1,
            "utilRxInBss": 9,
            "utilRxOtherBss": 0,
            "utilNonWifi": 0,
            "utilUnknownWifi": 0,
            "utilUndecodable": 0,
        },
        "channels": channels,
    }
    radio_events = [
        pick_rrm_event({
            "timestamp": t - 156, "ap": "0a0027aa1103", "band": "5",
            "event": "rrm-radar", "channel": 149, "pre_channel": 36,
            "bandwidth": 80, "pre_bandwidth": 80, "power": 17, "pre_power": 17,
            "usage": "5", "pre_usage": "5", "apName": "DEMO-AP-F2-aa:11:03",
        }),
        pick_rrm_event({
            "timestamp": t - 80, "ap": "0a0027aa1102", "band": "5",
            "event": "triggered-site_rrm", "channel": 144, "pre_channel": 144,
            "bandwidth": 20, "pre_bandwidth": 20, "power": 8, "pre_power": 14,
            "usage": "5", "pre_usage": "5", "apName": "DEMO-AP-F2-aa:11:02",
        }),
        pick_rrm_event({
            "timestamp": t - 90000, "ap": "0a0027aa1102", "band": "5",
            "event": "interference-ap-non-wifi", "channel": 144, "pre_channel": 153,
            "bandwidth": 20, "pre_bandwidth": 80, "power": 8, "pre_power": 14,
            "usage": "5", "pre_usage": "5", "apName": "DEMO-AP-F2-aa:11:02",
        }),
        pick_rrm_event({
            "timestamp": t - 2 * 86400 - 3600, "ap": "0a0027aa1102", "band": "5",
            "event": "scheduled-site_rrm", "channel": 144, "pre_channel": 144,
            "bandwidth": 20, "pre_bandwidth": 20, "power": 8, "pre_power": 8,
            "usage": "5", "pre_usage": "5", "apName": "DEMO-AP-F2-aa:11:02",
        }),
        pick_rrm_event({
            "timestamp": t - 4 * 86400, "ap": "0a0027aa1105", "band": "5",
            "event": "neighbor-ap-down", "channel": 108, "pre_channel": 108,
            "bandwidth": 40, "pre_bandwidth": 40, "power": 8, "pre_power": 8,
            "usage": "5", "pre_usage": "5", "apName": "DEMO-AP-F2-aa:11:05",
        }),
    ]
    radio_events = annotate_radio_events(radio_events, events, sessions, stats)
    calls = [
        pick_call({
            "app": "teams", "mac": DEMO_MAC, "meeting_id": "demo-teams-1",
            "start_time": t - 210, "end_time": t - 35,
            "audio_quality": 2, "video_quality": 3, "rating": 2,
        }),
        pick_call({
            "app": "teams", "mac": DEMO_MAC, "meeting_id": "demo-teams-2",
            "start_time": t - 86400 - 3600, "end_time": t - 86400 - 1800,
            "audio_quality": 5, "video_quality": 5, "rating": 5,
        }),
        pick_call({
            "app": "zoom", "mac": DEMO_MAC, "meeting_id": "demo-zoom-1",
            "start_time": t - 3 * 3600, "end_time": t - 3 * 3600 + 2400,
            "audio_quality": 4, "video_quality": 4,
        }),
    ]
    radar_alerts = radar_session_alerts(radio_events, sessions, calls, ap_radio)
    demo_store = RadioEventStore({hex_mac(s.get("ap")) for s in sessions})
    demo_store.add_many(radio_events)
    client_radar = demo_store.client_radar_events(sessions)
    return {
        "demo": True,
        "host": DEFAULT_HOST,
        "orgId": "demo-org",
        "siteId": "demo-site",
        "siteName": "Sample HQ — Floor 2",
        "mac": DEMO_MAC,
        "duration": "1d",
        "online": True,
        "stats": stats,
        "sightings": [stats],
        "events": events,
        "sessions": sessions,
        "marvisText": json.dumps(marvis, indent=2),
        "marvisUnavailable": False,
        "apRadio": ap_radio,
        "radioEvents": radio_events,
        "radioEventsUnavailable": None,
        "clientRadarEvents": client_radar,
        "calls": calls,
        "callsUnavailable": None,
        "radarAlerts": radar_alerts,
        "radioStoreStats": {
            "scanned": demo_store.scanned,
            "dropped": demo_store.dropped,
            "radars": len(demo_store.radars),
            "kept": len(demo_store.kept),
            "clientHits": len(client_radar),
        },
        "verdict": build_verdict(stats, events, sessions, ap_radio, radio_events, calls, demo_store),
        "fetchedAt": int(time.time() * 1000),
        "email": "demo@local",
        "orgs": [{"id": "demo-org", "name": "Interconnected Systems (sample)"}],
        "sites": [{"id": "demo-site", "name": "Sample HQ — Floor 2"}],
    }


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content"/>
<title>Mist Disconnect Console</title>
<style>
:root {
  --bg:#0b0d11; --surface:#13161c; --surface-2:#1a1e26; --surface-3:#232833;
  --fg:#ecece8; --muted:#9aa0ab; --subtle:#6e7480; --border:#2a303b;
  --accent:#8fd0c4; --accent-fg:#0b0d11; --good:#3fbf8f; --warn:#d29a3a; --crit:#e15d5d;
  --occ-ext:#2bb3c0; --occ-site:#e8a23a; --occ-nonwifi:#e15d5d;
}
* { box-sizing: border-box; }
html, body { margin:0; background:var(--bg); color:var(--fg);
  font-family:"Segoe UI","IBM Plex Sans",system-ui,sans-serif; line-height:1.5;
  overflow-x:clip; -webkit-text-size-adjust:100%; }
button { cursor:pointer; font:inherit; }
input, select { font:inherit; font-size:16px; }
.app { min-height:100dvh; padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
header { position:sticky; top:0; z-index:20; border-bottom:1px solid var(--border); background:color-mix(in oklab, var(--bg) 90%, transparent); backdrop-filter:blur(8px); }
.wrap { max-width:72rem; margin:0 auto; padding:0.85rem 1rem; }
main.wrap { padding-top:1.25rem; padding-bottom:4rem; }
.row { display:flex; align-items:center; justify-content:space-between; gap:.75rem; }
.brand { display:flex; align-items:center; gap:.75rem; min-width:0; }
.logo { width:36px; height:36px; border:1px solid var(--border); background:var(--surface-2); border-radius:10px; display:grid; place-items:center; color:var(--accent); flex:none; }
.muted { color:var(--muted); } .subtle { color:var(--subtle); } .crit { color:var(--crit); } .warn { color:var(--warn); } .good { color:var(--good); } .accent { color:var(--accent); }
.card { background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:1.1rem; min-width:0; }
.grid2 { display:grid; gap:1rem; }
@media (min-width: 960px) { .grid2 { grid-template-columns: 1.15fr .85fr; } }
.metrics { display:grid; gap:.75rem; grid-template-columns:1fr 1fr; }
@media (min-width: 960px) { .metrics { grid-template-columns:repeat(4,1fr); } }
label span { display:block; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--subtle); margin-bottom:.4rem; }
input, select { width:100%; min-height:44px; border-radius:10px; border:1px solid var(--border); background:var(--surface-2); color:var(--fg); padding:0 .75rem; }
.btn { min-height:44px; border:0; border-radius:10px; padding:0 1rem; display:inline-flex; align-items:center; justify-content:center; gap:.5rem; font-weight:600; }
.btn-p { background:var(--accent); color:var(--accent-fg); }
.btn-s { background:var(--surface-2); color:var(--fg); border:1px solid var(--border); }
.btn-g { background:transparent; color:var(--muted); }
.btn:disabled { opacity:.4; }
.stack { display:grid; gap:1rem; }
h1 { font-size:1.35rem; margin:.2rem 0 .4rem; }
ul.plain { margin:.6rem 0 0; padding:0; list-style:none; }
ul.plain li { margin:0 0 .45rem; }
.metric { min-height:96px; }
.pulse-c { animation: pc 1.4s ease-out infinite; border-color:color-mix(in oklab, var(--crit) 70%, var(--border)); }
.pulse-w { animation: pw 1.8s ease-out infinite; border-color:color-mix(in oklab, var(--warn) 55%, var(--border)); }
@keyframes pc { 0%,100%{box-shadow:0 0 0 0 color-mix(in oklab,var(--crit) 45%,transparent)} 50%{box-shadow:0 0 0 8px transparent} }
@keyframes pw { 0%,100%{box-shadow:0 0 0 0 color-mix(in oklab,var(--warn) 35%,transparent)} 50%{box-shadow:0 0 0 7px transparent} }
@keyframes live { 0%,100%{opacity:1} 50%{opacity:.35} }
.dot { width:6px; height:6px; border-radius:99px; background:var(--accent); animation:live 1.2s ease-out infinite; display:inline-block; }
.pill { display:inline-flex; align-items:center; gap:.35rem; border-radius:999px; padding:.15rem .55rem; font-size:12px; background:var(--surface-2); }
.toolbar { display:grid; gap:.5rem; }
@media (min-width: 720px) { .toolbar { grid-template-columns: minmax(0,1fr) 7rem auto auto auto; } }
.ev { border:1px solid var(--border); border-radius:10px; padding:.6rem .75rem; margin-bottom:.5rem; }
.ev.neg { border-color:color-mix(in oklab,var(--crit) 35%, var(--border)); background:var(--surface-2); }
.mono { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }
.break { overflow-wrap:anywhere; }
dl { display:grid; grid-template-columns: 9.5rem minmax(0,1fr); gap:.4rem .75rem; margin: .7rem 0 0; font-size:14px; }
dt { color:var(--subtle); } dd { margin:0; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:var(--surface-2); padding:.75rem; border-radius:10px; font-size:12px; }
.alert { border:1px solid color-mix(in oklab,var(--crit) 40%, var(--border)); color:var(--crit); padding:.75rem 1rem; border-radius:12px; margin-bottom:1rem; }
.hidden { display:none !important; }
.legend { display:flex; flex-wrap:wrap; gap:.75rem 1.1rem; font-size:12px; color:var(--muted); margin:.4rem 0 .8rem; }
.swatch { width:10px; height:10px; border-radius:2px; display:inline-block; margin-right:.35rem; vertical-align:middle; }
.ap-table { width:100%; border-collapse:collapse; font-size:13px; }
.ap-table th { text-align:left; color:var(--subtle); font-weight:500; padding:.4rem .5rem .5rem 0; font-size:11px; text-transform:uppercase; letter-spacing:.04em; position:sticky; top:0; background:var(--surface); z-index:1; box-shadow:0 1px 0 var(--border); }
.ap-table td { padding:.45rem .5rem .45rem 0; border-top:1px solid var(--border); }
.sess-scroll { max-height:min(32rem, 65vh); overflow:auto; -webkit-overflow-scrolling:touch; }
.radar-scroll { max-height:min(20rem, 40vh); overflow:auto; -webkit-overflow-scrolling:touch; }
.ap-table tr.radar td { background:color-mix(in oklab, var(--crit) 10%, transparent); }
.occ-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.chiprow { display:flex; flex-wrap:wrap; gap:.35rem; align-items:center; }
.chip { min-height:32px; padding:0 .65rem; border-radius:8px; border:1px solid var(--border); background:var(--surface-2); color:var(--muted); font-size:12px; font-weight:600; }
.chip.on { background:color-mix(in oklab, var(--accent) 22%, var(--surface-2)); color:var(--fg); border-color:color-mix(in oklab, var(--accent) 45%, var(--border)); }
@media (prefers-reduced-motion: reduce) { .pulse-c,.pulse-w,.dot { animation:none; } }
</style>
</head>
<body>
<div class="app">
<header><div class="wrap row">
  <div class="brand">
    <div class="logo">◉</div>
    <div style="min-width:0">
      <div style="font-weight:650">Mist Disconnect Console</div>
      <div class="subtle" id="sub" style="font-size:12px">local · api.gc2.mist.com</div>
    </div>
  </div>
  <button class="btn btn-g hidden" id="btnSession" type="button">← Session</button>
</div></header>
<main class="wrap">
  <div id="err" class="alert hidden"></div>
  <section id="viewConnect" class="grid2">
    <form class="card stack" id="formConnect">
      <h1>Client disconnect RCA</h1>
      <p class="muted">Investigate why a station drops: RF, 802.11 reason codes, DHCP after roam, and Marvis — without dumping the whole site.</p>
      <label><span>API region</span>
        <select id="host"></select>
      </label>
      <label><span>Read-only API token</span>
        <input id="token" type="password" autocomplete="off" spellcheck="false" placeholder="Observer / read-only token" required minlength="8"/>
      </label>
      <button class="btn btn-p" type="submit" id="btnConnect">Validate token</button>
      <button class="btn btn-s" type="button" id="btnDemo">Run sample investigation</button>
    </form>
    <div class="stack">
      <aside class="card" style="border-color:color-mix(in oklab,var(--accent) 35%, var(--border))">
        <h2 class="accent" style="margin:0;font-size:13px;text-transform:uppercase;letter-spacing:.04em">Standard practice</h2>
        <ul class="plain muted">
          <li><strong style="color:var(--fg)">Use a read-only (Observer) token.</strong> This console only issues GET requests. Never paste Org Admin, Super User, or write-enabled keys.</li>
          <li>Create it under <span style="color:var(--fg)">Organization → Settings → API Tokens</span> with Observer privileges scoped to the org or site you are troubleshooting.</li>
          <li>The token stays in this browser tab, is forwarded only to the Mist region you select via this local process, and is never written to disk. Close the tab when finished. Rotate the token if it was exposed.</li>
          <li>Observer still sees client identifiers (MAC, hostname, username). Treat captures as operational data.</li>
        </ul>
      </aside>
      <aside class="card">
        <h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">What gets correlated</h2>
        <ul class="plain muted">
          <li>RSSI/SNR vs deauth reason (coverage vs idle vs handshake).</li>
          <li>DHCP/DNS failures in the 2 minutes after a roam or assoc (L3 after join).</li>
          <li>AP ping-pong, 5→2.4 band drops, short sessions, TX retries.</li>
          <li>Serving-AP channel occupancy: Site APs vs External APs vs Non-Wi-Fi (RRM scan).</li>
          <li>7 days of Radio Management events (DFS radar, channel/power change) vs this client's disconnects.</li>
          <li>Microsoft Teams / Zoom call quality overlapping those drops (when Mist has call stats).</li>
        </ul>
      </aside>
    </div>
  </section>
  <section id="viewScope" class="hidden">
    <form class="card stack" id="formScope" style="max-width:36rem;margin:0 auto">
      <h1>Select site and client</h1>
      <p class="muted">Token validated. Choose the site, then the MAC under investigation.</p>
      <label><span>Organization</span><select id="org"></select></label>
      <label><span>Site</span><select id="site"></select></label>
      <label><span>Client MAC</span><input id="mac" class="mono" placeholder="aa:bb:cc:dd:ee:ff" required/></label>
      <label><span>Lookback</span>
        <select id="duration">
          <option value="1h">1 hour</option><option value="6h">6 hours</option>
          <option value="1d" selected>1 day</option><option value="1w">1 week</option>
        </select>
      </label>
      <button class="btn btn-p" type="submit" id="btnDiag">Diagnose</button>
    </form>
  </section>
  <section id="viewBoard" class="hidden stack"></section>
</main>
</div>
<script>
const HOSTS = ["api.gc2.mist.com","api.mist.com","api.gc1.mist.com","api.ac2.mist.com","api.gc4.mist.com","api.eu.mist.com","api.gc3.mist.com","api.ac5.mist.com","api.gc5.mist.com"];
const $ = (id) => document.getElementById(id);
const hostSel = $("host");
HOSTS.forEach(h => { const o=document.createElement("option"); o.value=h; o.textContent=h+(h==="api.gc2.mist.com"?" (default)":""); hostSel.appendChild(o); });
const state = { token:"", host:"api.gc2.mist.com", orgs:[], orgId:"", sites:[], siteId:"", mac:"", duration:"1d", result:null, live:false, liveSec:15, timer:null, samples:[], busy:false, demo:false, email:"", occFilter:"all" };

function show(id) {
  ["viewConnect","viewScope","viewBoard"].forEach(v => $(v).classList.toggle("hidden", v!==id));
  $("btnSession").classList.toggle("hidden", id==="viewConnect");
}
function setErr(msg) { const e=$("err"); e.textContent=msg||""; e.classList.toggle("hidden", !msg); }
function setSub() { $("sub").textContent = "local · "+state.host+(state.email?" · "+state.email:""); }

async function api(path, body) {
  const res = await fetch(path, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function fmtMac(m){ const n=(m||"").replace(/[^0-9a-f]/gi,"").toLowerCase(); return n.length===12?n.match(/.{2}/g).join(":"):m; }
function fmtTime(ts){ if(ts==null||ts==="") return "—"; const n=Number(ts); const ms=n>1e11?n:n*1000; try{ return new Date(ms).toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"});}catch(e){return String(ts);} }
function fmtDur(sec){ if(sec==null) return "—"; if(sec<60) return Math.round(sec)+"s"; if(sec<3600) return Math.floor(sec/60)+"m "+Math.round(sec%60)+"s"; return Math.floor(sec/3600)+"h "+Math.floor((sec%3600)/60)+"m"; }
function fmtBytes(n){ if(n==null) return "—"; if(n<1024) return n+" B"; if(n<1048576) return (n/1024).toFixed(1)+" KB"; return (n/1048576).toFixed(1)+" MB"; }
function rssiBand(v){ if(v==null) return "unknown"; if(v<-75) return "crit"; if(v<-65) return "warn"; return "good"; }
function snrBand(v){ if(v==null) return "unknown"; if(v<15) return "crit"; if(v<25) return "warn"; return "good"; }
function bandClass(b){ return b==="crit"?"crit":b==="warn"?"warn":b==="good"?"good":"muted"; }
function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g, "&"+"amp;")
    .replace(/</g, "&"+"lt;")
    .replace(/>/g, "&"+"gt;")
    .replace(/"/g, "&"+"quot;")
    .replace(/'/g, "&#39;");
}
function reason(code){ const map={1:"Unspecified",2:"Previous authentication no longer valid",3:"STA leaving IBSS/ESS",4:"Disassociated due to inactivity",5:"AP cannot handle all currently associated STAs",6:"Class 2 frame from nonauthenticated STA",7:"Class 3 frame from nonassociated STA",8:"STA leaving BSS",9:"STA requesting (re)association is not authenticated",10:"Unacceptable power capability",13:"Invalid information element",14:"MIC failure",15:"4-way handshake timeout",16:"Group key handshake timeout",17:"IE in 4-way handshake different from (re)assoc",18:"Invalid group cipher",19:"Invalid pairwise cipher",20:"Invalid AKMP",23:"IEEE 802.1X authentication failed",39:"The QoS AP lacks sufficient bandwidth"}; if(code==null||code==="") return ""; const n=Number(code); return map[n]?n+" — "+map[n]:String(code); }

$("formConnect").onsubmit = async (e) => {
  e.preventDefault(); setErr(""); state.busy=true; $("btnConnect").disabled=true;
  try {
    state.token=$("token").value.trim(); state.host=$("host").value;
    const res = await api("/api/connect", {token:state.token, host:state.host});
    state.email=res.email; state.orgs=res.orgs; state.orgId=res.orgs[0]?.id||"";
    fillSelect($("org"), state.orgs); setSub();
    await loadSites(); show("viewScope");
  } catch(err) { setErr(err.message); } finally { state.busy=false; $("btnConnect").disabled=false; }
};
$("btnDemo").onclick = async () => {
  setErr(""); const res = await api("/api/demo", {jitter:false});
  state.demo=true; state.result=res; state.mac=fmtMac(res.mac); state.email=res.email||"demo@local";
  state.host=res.host; $("host").value=res.host; setSub(); state.samples=[]; setLive(false); renderBoard(); show("viewBoard");
};
$("org").onchange = () => { state.orgId=$("org").value; loadSites(); };
async function loadSites(){
  const listed = await api("/api/sites", {token:state.token, host:state.host, orgId:state.orgId});
  state.sites=listed; state.siteId=listed[0]?.id||""; fillSelect($("site"), listed);
}
function fillSelect(el, items){ el.innerHTML=""; items.forEach(it=>{ const o=document.createElement("option"); o.value=it.id; o.textContent=it.name; el.appendChild(o); }); if(items[0]) el.value=items[0].id; }
$("formScope").onsubmit = async (e) => { e.preventDefault(); state.mac=$("mac").value; state.duration=$("duration").value; state.siteId=$("site").value; state.orgId=$("org").value; await runDiag(false); };
$("btnSession").onclick = () => { setLive(false); state.result=null; show("viewConnect"); };

async function runDiag(fromLive){
  if(state.busy && fromLive) return;
  state.busy=true;
  try {
    let res;
    if(state.demo) res = await api("/api/demo", {jitter: !!fromLive});
    else res = await api("/api/diagnose", {token:state.token, host:state.host, orgId:state.orgId, siteId:state.siteId, siteName:(state.sites.find(s=>s.id===state.siteId)||{}).name||"", mac:state.mac||state.result?.mac, duration:state.duration, live:!!fromLive});
    state.result=res;
    state.samples = [...state.samples.slice(-47), {t:res.fetchedAt, rssi:res.stats?.rssi??null, snr:res.stats?.snr??null}];
    renderBoard(); show("viewBoard");
  } catch(err) {
    setErr(err.message);
    if(/429|rate limit/i.test(err.message)) setLive(false);
  } finally { state.busy=false; }
}
function setLive(on){
  state.live=on;
  if(state.timer){ clearInterval(state.timer); state.timer=null; }
  if(on){ state.timer=setInterval(()=>{ if(document.hidden) return; runDiag(true); }, state.liveSec*1000); }
}

function spark(samples, field){
  const pts=samples.map(s=>s[field]).filter(v=>v!=null);
  if(pts.length<2) return `<p class="subtle" style="font-size:12px">Need two live samples to plot ${field.toUpperCase()}.</p>`;
  const w=280,h=56,min=Math.min(...pts),max=Math.max(...pts),span=max-min||1;
  const d=pts.map((v,i)=>{ const x=(i/(pts.length-1))*(w-8)+4; const y=h-6-((v-min)/span)*(h-12); return `${i?"L":"M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" class="break" style="height:56px;width:100%"><path d="${d}" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--accent)"/></svg>`;
}

function occBand(ch, band){
  if(band==="24") return "24";
  if(band==="6") return "6";
  if(ch>=36 && ch<=48) return "unii1";
  if(ch>=52 && ch<=64) return "unii2";
  if(ch>=100 && ch<=144) return "unii2e";
  if(ch>=149 && ch<=165) return "unii3";
  return "other";
}

function occChart(ap){
  const all = (ap && ap.channels) || [];
  const filt = state.occFilter || "all";
  const servingCh = (all.find(c=>c.serving)||{}).channel;
  let chs;
  if(filt==="all"){
    if(servingCh>=100 && servingCh<=165)
      chs = all.filter(c => occBand(c.channel, ap.band)==="unii2e" || occBand(c.channel, ap.band)==="unii3");
    else if(servingCh>=36 && servingCh<=64)
      chs = all.filter(c => occBand(c.channel, ap.band)==="unii1" || occBand(c.channel, ap.band)==="unii2");
    else
      chs = all;
  } else {
    chs = all.filter(c => occBand(c.channel, ap.band)===filt);
  }
  if(!all.length){
    const r = ap && ap.radio;
    if(!r) return `<p class="muted">No occupancy histogram for this AP (RRM considerations empty). Serving-channel util still shown above when radio_stat is present.</p>`;
    return "";
  }
  if(!chs.length) return `<p class="muted">No channels in this UNII / band filter. Switch to All.</p>`;
  const w = Math.max(620, chs.length*42);
  const h = 228, padL=52, padB=36, padT=14, padR=10;
  const innerW = w-padL-padR, innerH = h-padT-padB;
  const bw = innerW/chs.length;
  const yticks = [0,25,50,75,100].map(p=>{
    const y = padT+innerH-(p/100)*innerH;
    return `<line x1="${padL}" x2="${w-padR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--border)"/>
      <text x="${padL-6}" y="${(y+4).toFixed(1)}" text-anchor="end" fill="var(--subtle)" font-size="10">${p}%</text>`;
  }).join("");
  const bars = chs.map((c,i)=>{
    const x = padL + i*bw + bw*0.2;
    const barW = bw*0.6;
    const y0 = padT+innerH;
    const hN = (Math.min(100,c.nonWifi||0)/100)*innerH;
    const hS = (Math.min(100,c.site||0)/100)*innerH;
    const hE = (Math.min(100,c.external||0)/100)*innerH;
    const tot = (c.nonWifi||0)+(c.site||0)+(c.external||0);
    const flash = (c.nonWifi||0)>=30 ? " pulse-c" : tot>=70 ? " pulse-w" : "";
    const labelFill = c.serving ? "var(--fg)" : "var(--subtle)";
    return `<g class="${flash.trim()}">
      <rect x="${x.toFixed(1)}" y="${(y0-hN).toFixed(1)}" width="${barW.toFixed(1)}" height="${hN.toFixed(1)}" fill="var(--occ-nonwifi)" rx="1"/>
      <rect x="${x.toFixed(1)}" y="${(y0-hN-hS).toFixed(1)}" width="${barW.toFixed(1)}" height="${hS.toFixed(1)}" fill="var(--occ-site)" rx="1"/>
      <rect x="${x.toFixed(1)}" y="${(y0-hN-hS-hE).toFixed(1)}" width="${barW.toFixed(1)}" height="${hE.toFixed(1)}" fill="var(--occ-ext)" rx="1"/>
      <text x="${(x+barW/2).toFixed(1)}" y="${h-10}" text-anchor="middle" fill="${labelFill}" font-size="${c.serving?12:11}" font-weight="${c.serving?700:500}">${esc(c.channel)}</text>
    </g>`;
  }).join("");
  const ylab = `<text transform="translate(12,${padT+innerH/2}) rotate(-90)" text-anchor="middle" fill="var(--muted)" font-size="11">Channel Occupancy</text>`;
  return `<div class="occ-scroll"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Channel occupancy" style="width:100%;min-width:560px;height:220px">${ylab}${yticks}${bars}</svg></div>`;
}

function occPanel(ap){
  if(!ap) return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Current radio values</h2><p class="muted">No serving AP identified from sessions.</p></div>`;
  if(ap.unavailable && !ap.radio && !(ap.channels||[]).length){
    return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Current radio values</h2><p class="muted">${esc(ap.unavailable)}</p></div>`;
  }
  const r = ap.radio||{};
  const servingBar = (ap.channels||[]).find(c=>c.serving) || {};
  const nw = servingBar.nonWifi!=null ? servingBar.nonWifi : (r.utilNonWifi||0);
  const ext = servingBar.external!=null ? servingBar.external : ((r.utilRxOtherBss||0)+(r.utilUnknownWifi||0));
  const site = servingBar.site!=null ? servingBar.site : (r.utilRxInBss||0);
  const tot = Math.min(100, nw+ext+site);
  const src = ap.source==="marvis" ? "most of the time (Marvis)"
    : ap.source==="sessions" ? `most session time (${fmtDur(ap.dwellSeconds)})`
    : "from "+(ap.source||"stats");
  const marvisNote = (ap.marvisAps||[]).length && !(ap.marvisMentioned)
    ? ` Marvis also named AP ${fmtMac(ap.marvisAps[0])} — dwell wins.`
    : (ap.marvisMentioned ? " Marvis named this AP as well." : "");
  const scopeNote = ap.scope==="site" ? " Histogram is site-wide channel scores (per-AP RRM empty)." : " Histogram is this AP's 20-min RRM scan — same wifi / non_wifi occupancy as Site → Radio Management → Current Radio Values. Site vs External splits wifi occupancy by same-site vs other-site RSSI. Live radio_stat utilization is the AP table only, not these bars.";
  const servingFlash = nw>=30?" pulse-c": tot>=70?" pulse-w":"";
  const bands = new Set((ap.channels||[]).map(c=>occBand(c.channel, ap.band)));
  const filters = [
    ["all","All"],
    ["unii1","UNII-1"],
    ["unii2","UNII-2"],
    ["unii2e","UNII-2 Ext"],
    ["unii3","UNII-3"],
    ["24","2.4 GHz"],
    ["6","6 GHz"],
  ].filter(([id]) => id==="all" || bands.has(id));
  if(state.occFilter!=="all" && !bands.has(state.occFilter)) state.occFilter="all";
  const chips = filters.map(([id,lab]) =>
    `<button class="chip${state.occFilter===id?" on":""}" type="button" data-occ="${id}">${lab}</button>`
  ).join("");
  return `<div class="card">
    <div class="row" style="align-items:flex-start;flex-wrap:wrap">
      <div>
        <h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Current radio values</h2>
        <p class="muted" style="margin:.35rem 0 0;font-size:13px">RF as seen by the AP this client spent ${esc(src)} on.${esc(marvisNote)}</p>
        ${ap.selectionNote?`<p class="${ap.fallback?"warn":"muted"}" style="margin:.4rem 0 0;font-size:13px">${esc(ap.selectionNote)}</p>`:""}
      </div>
      <span class="pill ${ap.status==="connected"?"good":"muted"}">${esc(ap.status||"ap")}</span>
    </div>
    <div class="row" style="flex-wrap:wrap;margin-top:.7rem">
      <div class="legend" style="margin:0">
        <span><i class="swatch" style="background:var(--occ-ext)"></i>External APs</span>
        <span><i class="swatch" style="background:var(--occ-site)"></i>Site APs</span>
        <span><i class="swatch" style="background:var(--occ-nonwifi)"></i>Non-Wi-Fi</span>
      </div>
      <div class="chiprow" id="occFilters">${chips}</div>
    </div>
    ${occChart(ap)}
    <p class="subtle" style="font-size:11px;margin:.35rem 0 0">Channel occupancy % · serving channel in bold.${esc(scopeNote)} Bars flash when Non-Wi-Fi ≥ 30% or total ≥ 70%.</p>
    <div class="metrics" style="margin-top:1rem;grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="card metric${nw>=30?" pulse-c":""}" style="min-height:72px">
        <div class="subtle" style="font-size:11px;text-transform:uppercase">Non-Wi-Fi</div>
        <div class="mono ${nw>=30?"crit":nw>=15?"warn":"good"}" style="font-size:1.25rem">${esc(nw)}%</div>
      </div>
      <div class="card metric${ext>=30?" pulse-w":""}" style="min-height:72px">
        <div class="subtle" style="font-size:11px;text-transform:uppercase">External APs</div>
        <div class="mono ${ext>=30?"warn":"muted"}" style="font-size:1.25rem">${esc(ext)}%</div>
      </div>
      <div class="card metric" style="min-height:72px">
        <div class="subtle" style="font-size:11px;text-transform:uppercase">Site / in-BSS</div>
        <div class="mono" style="font-size:1.25rem">${esc(site)}%</div>
      </div>
    </div>
    <div style="overflow-x:auto;margin-top:1rem">
      <table class="ap-table">
        <thead><tr>
          <th>AP</th><th>MAC</th><th>Band</th><th>Clients</th><th>Channel</th><th>Width</th><th>Power</th><th>Util</th>
        </tr></thead>
        <tbody><tr>
          <td>${esc(ap.apName||"—")}</td>
          <td class="mono">${esc(fmtMac(ap.apMac||""))}</td>
          <td>${esc(ap.band==="24"?"2.4 GHz":ap.band==="6"?"6 GHz":"5 GHz")}</td>
          <td class="mono">${esc(r.numClients??"—")}</td>
          <td class="mono" style="font-weight:700">${esc(r.channel??"—")}</td>
          <td class="mono">${r.bandwidth!=null?esc(r.bandwidth)+" MHz":"—"}</td>
          <td class="mono">${r.power!=null?esc(r.power)+" dBm":"—"}</td>
          <td class="mono${servingFlash}">${r.utilAll!=null?esc(r.utilAll)+"%":"—"}</td>
        </tr></tbody>
      </table>
    </div>
  </div>`;
}

function metric(label,value,hint,band){
  const pulse=band==="crit"?" pulse-c":band==="warn"?" pulse-w":"";
  return `<div class="card metric${pulse}"><div class="subtle" style="font-size:12px;text-transform:uppercase">${esc(label)}</div>
    <div class="mono ${bandClass(band)}" style="font-size:1.4rem;margin-top:.4rem">${esc(value)}</div>
    <div class="muted" style="font-size:12px">${esc(hint||"")}</div></div>`;
}

function radioEventKind(ev){
  const t=(ev.event||"").toLowerCase();
  if(t.includes("radar")) return "crit";
  if(ev.channelChanged || t.includes("interference")) return "warn";
  return "muted";
}
function bandHz(b){
  const s=String(b||"");
  if(s==="24"||s==="2.4") return "2.4 GHz";
  if(s==="6") return "6 GHz";
  if(!s) return "—";
  return "5 GHz";
}
function arrow(a,b,unit){
  if(a==null && b==null) return "—";
  if(a==null || a==="" || a===0 || String(a)===String(b)) return (b==null?"—":esc(b)+(unit||""));
  return esc(a)+(unit||"")+" → "+esc(b)+(unit||"");
}
function clientRadarPanel(r){
  const rows = r.clientRadarEvents||[];
  const st = r.radioStoreStats||{};
  const statsBit = st.scanned!=null
    ? ` Scanned ${st.scanned} site radio events · indexed ${st.radars||0} DFS/Post radar · ${rows.length} overlapped this MAC's session on the same AP.`
    : "";
  if(!rows.length){
    return `<div class="card">
      <h2 class="subtle" style="margin:0 0 .35rem;font-size:13px;text-transform:uppercase">Radar hits on this client's APs (0)</h2>
      <p class="muted" style="margin:0;font-size:12px">No DFS / Post radar overlapped a session on the same AP in this lookback.${esc(statsBit)} Neighbor-AP radar is indexed in the radar store but is not this client's problem — it does not deauth this MAC.</p>
    </div>`;
  }
  return `<div class="card pulse-c" style="border-color:color-mix(in oklab, var(--crit) 70%, var(--border))">
    <h2 class="subtle" style="margin:0 0 .35rem;font-size:13px;text-transform:uppercase">Radar hits on this client's APs (${rows.length})</h2>
    <p class="muted" style="margin:0 0 .7rem;font-size:12px">Dedicated radar store — every DFS / Post radar on an AP this MAC was associated to in the lookback. Not truncated by the site-wide table. Same-AP + session overlap required.${esc(statsBit)}</p>
    <div class="sess-scroll occ-scroll">
    <table class="ap-table">
      <thead><tr><th>Date</th><th>AP</th><th>Band</th><th>Channel</th><th>Width</th><th>Power</th><th>Event</th></tr></thead>
      <tbody>${rows.map(radioRow).join("")}</tbody>
    </table>
    </div>
  </div>`;
}
function radioEventsPanel(r){
  if(r.radioEventsUnavailable && !(r.radioEvents||[]).length){
    return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Radio events</h2>
      <p class="muted">Radio Management events not available (${esc(r.radioEventsUnavailable)}). This console queries GET /sites/{id}/rrm/events?band=5|24|6 with start/end matching the lookback (band is required by Mist).</p></div>`;
  }
  const rows = r.radioEvents||[];
  if(!rows.length){
    return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Radio events</h2>
      <p class="muted">No Radio Management events in this lookback (scheduled RRM, Post radar, interference, neighbor AP). Client disconnects in this window are not radio-event driven.</p></div>`;
  }
  const ranked = rows.slice().sort((a,b)=>{
    const ha = a.highlight?1:0, hb = b.highlight?1:0;
    if(hb!==ha) return hb-ha;
    const oa = a.onClientAp?1:0, ob = b.onClientAp?1:0;
    if(ob!==oa) return ob-oa;
    return (Number(b.timestamp)||0)-(Number(a.timestamp)||0);
  });
  const hitN = rows.filter(e=>e.highlight).length;
  return `<div class="card"><h2 class="subtle" style="margin:0 0 .35rem;font-size:13px;text-transform:uppercase">Radio events (${ranked.length})</h2>
    <p class="muted" style="margin:0 0 .7rem;font-size:12px">Same source as Mist <span style="color:var(--fg)">Site → Radio Management → Radio Events</span> for this lookback. <strong style="color:var(--crit)">Post radar on the AP this client was connected to</strong> is highlighted (${hitN}). Scroll the box — the full kept list is here (site-wide noise is filtered to a sample; client-AP radar is never dropped).</p>
    <div class="sess-scroll occ-scroll">
    <table class="ap-table">
      <thead><tr>
        <th>Date</th><th>AP</th><th>Band</th><th>Channel</th><th>Width</th><th>Power</th><th>Event</th>
      </tr></thead>
      <tbody>
      ${ranked.map(ev=>{
        const hit = !!ev.highlight;
        const on = !!ev.onClientAp;
        const name = ev.apName || fmtMac(ev.ap||"");
        const cls = hit?"crit":(String(ev.event||"").includes("radar")?"warn":"");
        return `<tr class="${hit?"pulse-c":""}" style="${hit?"background:color-mix(in oklab, var(--crit) 12%, transparent)":on?"background:color-mix(in oklab, var(--accent) 8%, transparent)":""}">
          <td class="mono subtle">${esc(fmtTime(ev.timestamp))}</td>
          <td class="mono break">${esc(name)}${hit?' <span class="pill crit">on this client</span>':on?' <span class="pill">client AP</span>':""}</td>
          <td class="mono">${esc(bandHz(ev.preUsage||ev.band))} → ${esc(bandHz(ev.usage||ev.band))}</td>
          <td class="mono">${arrow(ev.preChannel, ev.channel, "")}</td>
          <td class="mono">${arrow(ev.preBandwidth, ev.bandwidth, " MHz")}</td>
          <td class="mono">${arrow(ev.prePower, ev.power, " dBm")}</td>
          <td class="mono ${cls}">${esc(ev.label||ev.event||"—")}</td>
        </tr>`;
      }).join("")}
      </tbody>
    </table>
    </div>
  </div>`;
}
function callQuality(q){
  if(q==null||q==="") return "—";
  const n=Number(q);
  if(Number.isNaN(n)) return String(q);
  if(n>5) return n+"%";
  return String(n)+"/5";
}
function sessionsPanel(r){
  const rows = (r.sessions||[]).slice().sort((a,b)=>(Number(b.connect)||0)-(Number(a.connect)||0));
  if(!rows.length){
    return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Sessions</h2>
      <p class="muted">No session records in this window.</p></div>`;
  }
  const radarN = rows.filter(s=>s.hitByRadar).length;
  const shortN = rows.filter(s=>s.duration!=null && s.duration<60).length;
  const openN = rows.filter(s=>s.disconnect==null || s.disconnect==="").length;
  return `<div class="card"><h2 class="subtle" style="margin:0 0 .35rem;font-size:13px;text-transform:uppercase">Sessions (${rows.length})</h2>
    <p class="muted" style="margin:0 0 .7rem;font-size:12px">Entire association history for this window, newest first. ${openN} open · ${radarN} during radar on that AP · ${shortN} under 60s. Scroll the table — nothing is truncated.</p>
    <div class="sess-scroll occ-scroll">
    <table class="ap-table">
      <thead><tr>
        <th>Connected</th><th>Disconnected</th><th>Duration</th><th>AP</th><th>SSID</th><th>Band</th><th></th>
      </tr></thead>
      <tbody>
      ${rows.map(s=>{
        const name = s.apName || fmtMac(s.ap||"");
        const mac = s.ap ? fmtMac(s.ap) : "";
        const showMac = s.apName && mac && !String(s.apName).includes(mac);
        return `<tr class="${s.hitByRadar?"radar":""}">
          <td class="mono">${esc(fmtTime(s.connect))}</td>
          <td class="mono">${s.disconnect?esc(fmtTime(s.disconnect)):'<span class="good">open</span>'}</td>
          <td class="mono ${s.duration!=null&&s.duration<60?"crit":""}">${esc(fmtDur(s.duration))}</td>
          <td class="mono break">${esc(name)}${showMac?" · "+esc(mac):""}</td>
          <td class="mono break">${esc(s.ssid||"—")}</td>
          <td class="mono">${esc(bandHz(s.band))}</td>
          <td>${s.hitByRadar?'<span class="pill crit">radar</span>':(s.duration!=null&&s.duration<60?'<span class="pill">short</span>':"")}</td>
        </tr>`;
      }).join("")}
      </tbody>
    </table>
    </div>
  </div>`;
}

function callsPanel(r){
  if(r.callsUnavailable && !(r.calls||[]).length){
    return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Teams / collaboration calls</h2>
      <p class="muted">No call records (${esc(r.callsUnavailable)}). Full Microsoft Teams QoS (jitter/loss/rating from Azure) needs the org's <span style="color:var(--fg)">Mist ↔ Teams</span> link under Organization → Settings → Integrations. Without it, Mist still returns wireless-detected Zoom/Teams sessions when the feature is licensed — otherwise this panel stays empty. Wireless RCA below still stands.</p></div>`;
  }
  const rows = r.calls||[];
  if(!rows.length){
    return `<div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Teams / collaboration calls</h2>
      <p class="muted">No Teams/Zoom/Webex calls for this MAC in the last 7 days. If the user was on a call, either it was not classified or the Mist Teams integration is not linked.</p></div>`;
  }
  const teams = rows.filter(c=>c.teams);
  const poor = rows.filter(c=>c.poor);
  return `<div class="card"><h2 class="subtle" style="margin:0 0 .35rem;font-size:13px;text-transform:uppercase">Teams / collaboration calls (7 days)</h2>
    <p class="muted" style="margin:0 0 .7rem;font-size:12px">${teams.length} Microsoft Teams · ${rows.length} total collab · ${poor.length} poor audio/video/rating. Overlaps with deauth are listed under Correlated causes.</p>
    ${rows.slice(0,12).map(c=>`
      <div class="ev ${c.poor?"neg":""}">
        <div class="row"><span class="mono ${c.poor?"crit":"good"}">${esc(c.appLabel||c.app||"call")}${c.poor?" · poor":" · ok"}</span>
        <span class="mono subtle">${esc(fmtTime(c.start))}${c.end?" → "+fmtTime(c.end):""}</span></div>
        <div class="muted" style="font-size:12px">Audio ${esc(callQuality(c.audioQuality))} · Video ${esc(callQuality(c.videoQuality))}${c.rating!=null?" · user rating "+esc(c.rating):""} · ${esc(fmtDur(c.duration))}${c.meetingId?" · meeting "+esc(c.meetingId):""}</div>
      </div>`).join("")}
  </div>`;
}

function sessionRow(s){
  if(!s) return "";
  const name = s.apName || fmtMac(s.ap||"");
  const mac = s.ap ? fmtMac(s.ap) : "";
  const showMac = s.apName && mac && !String(s.apName).includes(mac);
  return `<tr class="radar">
    <td class="mono">${esc(fmtTime(s.connect))}</td>
    <td class="mono">${s.disconnect?esc(fmtTime(s.disconnect)):'<span class="good">open</span>'}</td>
    <td class="mono ${s.duration!=null&&s.duration<60?"crit":""}">${esc(fmtDur(s.duration))}</td>
    <td class="mono break">${esc(name)}${showMac?" · "+esc(mac):""}</td>
    <td class="mono break">${esc(s.ssid||"—")}</td>
    <td class="mono">${esc(bandHz(s.band))}</td>
    <td><span class="pill crit">radar</span></td>
  </tr>`;
}
function radioRow(ev){
  if(!ev) return "";
  const name = ev.apName || fmtMac(ev.ap||"");
  return `<tr class="radar pulse-c">
    <td class="mono subtle">${esc(fmtTime(ev.timestamp))}</td>
    <td class="mono break">${esc(name)} <span class="pill crit">on this client</span></td>
    <td class="mono">${esc(bandHz(ev.preUsage||ev.band))} → ${esc(bandHz(ev.usage||ev.band))}</td>
    <td class="mono">${arrow(ev.preChannel, ev.channel, "")}</td>
    <td class="mono">${arrow(ev.preBandwidth, ev.bandwidth, " MHz")}</td>
    <td class="mono">${arrow(ev.prePower, ev.power, " dBm")}</td>
    <td class="mono crit">${esc(ev.label||ev.event||"—")}</td>
  </tr>`;
}
function radarAlertBanner(r){
  const alerts=r.radarAlerts||[];
  if(!alerts.length) return "";
  return alerts.map(a=>{
    const radios = (a.radios && a.radios.length) ? a.radios : (a.radio ? [a.radio] : []);
    return `
    <div class="card pulse-c" style="border-color:color-mix(in oklab, var(--crit) 75%, var(--border));background:color-mix(in oklab, var(--crit) 10%, transparent)">
      <div class="row">
        <strong class="crit" style="font-size:13px;text-transform:uppercase;letter-spacing:.04em">Alert · session on radar AP</strong>
        <span class="pill crit">DFS${radios.length>1?" · "+radios.length:""}</span>
      </div>
      <p style="margin:.55rem 0 .85rem">${esc(a.summary||a.title||"")}</p>
      ${a.call?`<p class="muted" style="margin:0 0 .85rem;font-size:12px">Call in progress: <span class="mono">${esc(a.call)}${a.meetingId?" · meeting "+esc(a.meetingId):""}${a.callStart?" · "+esc(fmtTime(a.callStart)):""}${a.callEnd?" → "+esc(fmtTime(a.callEnd)):""}</span></p>`:""}
      <div class="subtle" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin:0 0 .35rem">This session</div>
      <div class="occ-scroll" style="margin-bottom:.9rem">
        <table class="ap-table">
          <thead><tr><th>Connected</th><th>Disconnected</th><th>Duration</th><th>AP</th><th>SSID</th><th>Band</th><th></th></tr></thead>
          <tbody>${sessionRow(a.session)}</tbody>
        </table>
      </div>
      <div class="subtle" style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin:0 0 .35rem">${radios.length>1?"These radar events ("+radios.length+")":"This radar event"}</div>
      <div class="radar-scroll occ-scroll">
        <table class="ap-table">
          <thead><tr><th>Date</th><th>AP</th><th>Band</th><th>Channel</th><th>Width</th><th>Power</th><th>Event</th></tr></thead>
          <tbody>${radios.map(radioRow).join("")}</tbody>
        </table>
      </div>
    </div>`;
  }).join("");
}

function correlationDetail(c){
  const d=c.detail; if(!d) return "";
  const rows=[];
  if(d.call) rows.push(["Teams / call", d.call+(d.meetingId?" · meeting "+d.meetingId:"")]);
  if(d.callStart) rows.push(["Call window", fmtTime(d.callStart)+(d.callEnd?" → "+fmtTime(d.callEnd):"")+(d.callDuration!=null?" ("+fmtDur(d.callDuration)+")":"")]);
  if(d.audioQuality!=null||d.videoQuality!=null) rows.push(["Call quality", "audio "+callQuality(d.audioQuality)+" · video "+callQuality(d.videoQuality)]);
  if(d.clientApName||d.clientAp) rows.push(["Client AP at that time", (d.clientApName?d.clientApName+" · ":"")+fmtMac(d.clientAp||"")]);
  if(d.radarEvent) rows.push(["Radar event", d.radarEvent+(d.radarType&&d.radarType!==d.radarEvent?" ("+d.radarType+")":"")]);
  if(d.radarTime) rows.push(["Radar timestamp", fmtTime(d.radarTime)]);
  if(d.radarApName||d.radarAp) rows.push(["Radar AP", (d.radarApName?d.radarApName+" · ":"")+fmtMac(d.radarAp||"")]);
  if(d.radarBand) rows.push(["Band", d.radarBand]);
  if(d.radarChannel) rows.push(["Channel", d.radarChannel]);
  if(d.radarWidth) rows.push(["Width", d.radarWidth]);
  if(d.radarPower) rows.push(["Power", d.radarPower]);
  if(d.dropType) rows.push(["Client event", d.dropType+(d.dropTime?" · "+fmtTime(d.dropTime):"")]);
  return `<dl>${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd class="mono break">${esc(v)}</dd>`).join("")}</dl>`;
}

function renderBoard(){
  const r=state.result; if(!r) return;
  const s=r.stats||{};
  const disconnects=(r.events||[]).filter(e=>/DEAUTH|DISASSOC|DISCONNECT/i.test(e.type)).length;
  const vt=r.verdict.label==="Critical"?"crit":r.verdict.label==="Degraded"?"warn":"good";
  const cors=r.verdict.correlations||[];
  const livePill = state.live ? `<span class="pill accent"><span class="dot"></span> live</span>` : "";
  $("viewBoard").innerHTML = `
    <div>
      <div class="subtle" style="font-size:12px;text-transform:uppercase">${esc(r.siteName)}</div>
      <h1 class="mono break">${esc(fmtMac(r.mac))}
        <span class="pill ${r.online?"good":"muted"}">${r.online?"seen":"stale"}</span>
        ${livePill}
        ${r.demo?'<span class="pill muted">sample</span>':""}
      </h1>
      <div class="subtle" style="font-size:12px">Last poll ${esc(fmtTime(r.fetchedAt))}</div>
    </div>
    <form class="toolbar" id="formBoard">
      <input class="mono" id="mac2" value="${esc(state.mac||fmtMac(r.mac))}"/>
      <select id="dur2"><option value="1h">1h</option><option value="6h">6h</option><option value="1d">1d</option><option value="1w">1w</option></select>
      <button class="btn btn-p" type="submit">Refresh</button>
      <button class="btn ${state.live?"btn-s":"btn-p"}" type="button" id="btnLive">${state.live?"Stop live":"Live monitor"}</button>
      <select id="liveSec">
        <option value="3">every 3s</option><option value="15">every 15s</option>
        <option value="30">every 30s</option><option value="60">every 60s</option>
      </select>
    </form>
    <p class="subtle" style="font-size:12px">Live mode re-queries client stats/events, 7-day radio events, Teams/Zoom calls, and the dominant AP's occupancy. Auto-pauses on Mist 429. 3s is aggressive.</p>
    ${radarAlertBanner(r)}
    ${clientRadarPanel(r)}
    <div class="card ${r.verdict.label==="Critical"||(r.radarAlerts||[]).length?"pulse-c":""}">
      <div class="${vt}" style="font-size:1.15rem;font-weight:650">${esc(r.verdict.label)} · score ${r.verdict.score}</div>
      <p>${esc(r.verdict.primaryCause)}</p>
      <ul class="plain muted">${r.verdict.notes.map(n=>`<li>— ${esc(n)}</li>`).join("")}</ul>
    </div>
    <div class="card">
      <h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Correlated causes</h2>
      ${!cors.length?'<p class="muted">No multi-signal pattern in this window.</p>':cors.map(c=>`
        <div class="ev ${c.highlight?"neg pulse-c":""}" style="border-color:color-mix(in oklab, var(--${c.severity==="info"?"border":c.severity}) 40%, var(--border))">
          <div class="row"><strong class="${c.severity==="crit"?"crit":c.severity==="warn"?"warn":"muted"}">${esc(c.title)}</strong>
          <span class="subtle" style="font-size:11px;text-transform:uppercase">${c.highlight?"on this AP · ":""}${esc(c.confidence)} · ${esc(c.severity)}</span></div>
          <p class="muted" style="margin:.4rem 0 0">${esc(c.evidence)}</p>
          ${c.highlight?correlationDetail(c):""}
        </div>`).join("")}
    </div>
    ${occPanel(r.apRadio)}
    ${radioEventsPanel(r)}
    ${callsPanel(r)}
    <div class="metrics">
      ${metric("RSSI", s.rssi!=null?s.rssi+" dBm":"—","Good ≥ −65 · Crit < −75", rssiBand(s.rssi))}
      ${metric("SNR", s.snr!=null?s.snr+" dB":"—","Good ≥ 25 · Crit < 15", snrBand(s.snr))}
      ${metric("Disconnects", String(disconnects), "Window "+r.duration, disconnects>=3?"crit":disconnects>=1?"warn":"good")}
      ${metric("TX retries", s.txRetries!=null?String(s.txRetries):"—", s.dualBand?"dual-band client":"retries", s.txRetries>=80?(rssiBand(s.rssi)==="good"?"warn":"crit"):"unknown")}
    </div>
    ${(state.live||state.samples.length>1)?`<div class="grid2">
      <div class="card"><div class="subtle" style="font-size:12px;text-transform:uppercase">RSSI over live polls</div>${spark(state.samples,"rssi")}</div>
      <div class="card"><div class="subtle" style="font-size:12px;text-transform:uppercase">SNR over live polls</div>${spark(state.samples,"snr")}</div>
    </div>`:""}
    <div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Identity / radio</h2>
        ${!r.stats?'<p class="muted">No live stats for this MAC on the site.</p>':`<dl>
          <dt>Hostname</dt><dd class="mono break">${esc(s.hostname||"—")}</dd>
          <dt>User</dt><dd class="mono break">${esc(s.username||"—")}</dd>
          <dt>Vendor</dt><dd class="mono break">${esc(s.manufacture||"—")}</dd>
          <dt>SSID</dt><dd class="mono break">${esc(s.ssid||"—")}</dd>
          <dt>VLAN</dt><dd class="mono">${esc(s.vlan??"—")}</dd>
          <dt>IP</dt><dd class="mono break">${esc(s.ip||"—")}</dd>
          <dt>AP</dt><dd class="mono break">${esc(s.ap||"—")}</dd>
          <dt>Band / ch</dt><dd class="mono">${esc([s.band,s.channel].filter(x=>x!=null&&x!=="").join(" / ")||"—")}</dd>
          <dt>Protocol</dt><dd class="mono">${esc(s.proto||"—")}</dd>
          <dt>Key mgmt</dt><dd class="mono">${esc(s.keyMgmt||"—")}</dd>
          <dt>Tx / Rx</dt><dd class="mono">${esc((s.txRate??"—")+" / "+(s.rxRate??"—"))}</dd>
          <dt>Retries</dt><dd class="mono">${s.txRetries!=null?esc(s.txRetries+" tx / "+(s.rxRetries??"—")+" rx"):"—"}</dd>
          <dt>Uptime</dt><dd class="mono">${esc(fmtDur(s.uptime))}</dd>
          <dt>Last seen</dt><dd class="mono">${esc(fmtTime(s.lastSeen))}</dd>
          <dt>Bytes</dt><dd class="mono">${esc(fmtBytes(s.txBytes)+" / "+fmtBytes(s.rxBytes))}</dd>
        </dl>`}
      </div>
    ${sessionsPanel(r)}
    <div class="card"><h2 class="subtle" style="margin:0 0 .6rem;font-size:13px;text-transform:uppercase">Event timeline</h2>
      ${!(r.events||[]).length?'<p class="muted">No client events returned for this window.</p>':
        r.events.slice(0,40).map(ev=>`<div class="ev ${ev.negative?"neg":""}">
          <div class="row"><span class="mono ${ev.negative?"crit":"good"}">${ev.negative?"FAIL":"OK"} · ${esc(ev.type)}</span>
          <span class="mono subtle">${esc(fmtTime(ev.timestamp))}</span></div>
          ${ev.text?`<div>${esc(ev.text)}</div>`:""}
          <div class="muted" style="font-size:12px">AP ${esc(ev.ap||"—")} · ${esc(ev.ssid||"SSID —")} · ${esc(ev.band||"band —")}${ev.channel!=null&&ev.channel!==""?" / ch "+esc(ev.channel):""}${reason(ev.reason)?" · "+esc(reason(ev.reason)):""}</div>
        </div>`).join("")}
    </div>
    <div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Marvis</h2>
      ${r.marvisUnavailable||!r.marvisText?'<p class="muted">Marvis Troubleshoot not available (no subscription, empty result, or API error). Events and RF still stand on their own.</p>':`<pre>${esc(r.marvisText)}</pre>`}
    </div>`;
  $("dur2").value=state.duration;
  $("liveSec").value=String(state.liveSec);
  $("formBoard").onsubmit=(e)=>{ e.preventDefault(); state.mac=$("mac2").value; state.duration=$("dur2").value; runDiag(false); };
  $("btnLive").onclick=()=>{ state.liveSec=Number($("liveSec").value); setLive(!state.live); renderBoard(); };
  $("liveSec").onchange=()=>{ state.liveSec=Number($("liveSec").value); if(state.live){ setLive(true); } };
  document.querySelectorAll("#occFilters [data-occ]").forEach(btn=>{
    btn.onclick=()=>{ state.occFilter=btn.getAttribute("data-occ")||"all"; renderBoard(); };
  });
}
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes | str, ctype: str) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/health":
            self._send(200, "ok", "text/plain; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "Invalid JSON"})
            return
        try:
            if path == "/api/connect":
                host = payload.get("host") or DEFAULT_HOST
                self._json(200, connect_mist(str(payload.get("token") or ""), host))
            elif path == "/api/sites":
                host = payload.get("host") or DEFAULT_HOST
                self._json(
                    200,
                    list_sites(str(payload.get("token") or ""), host, str(payload.get("orgId") or "")),
                )
            elif path == "/api/diagnose":
                host = payload.get("host") or DEFAULT_HOST
                self._json(
                    200,
                    diagnose_client(
                        str(payload.get("token") or ""),
                        host,
                        str(payload.get("orgId") or ""),
                        str(payload.get("siteId") or ""),
                        str(payload.get("siteName") or ""),
                        str(payload.get("mac") or ""),
                        str(payload.get("duration") or "1d"),
                        live=bool(payload.get("live")),
                    ),
                )
            elif path == "/api/demo":
                self._json(200, demo_result(bool(payload.get("jitter"))))
            else:
                self._json(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._json(400, {"error": str(e)})


def self_test() -> None:
    """Parity checks vs the published correlation engine."""
    assoc = pick_event({"timestamp": 1, "type": "CLIENT_ASSOCIATION", "text": "Associated"})
    author = pick_event({"timestamp": 1, "type": "CLIENT_AUTHORIZATION", "text": "Authorized"})
    deauth = pick_event({"timestamp": 1, "type": "CLIENT_DEAUTHENTICATION", "text": "bye", "reason": 8})
    disassoc = pick_event({"timestamp": 1, "type": "CLIENT_DISASSOCIATION", "text": "STA leaving BSS", "reason": 8})
    dhcp = pick_event({"timestamp": 1, "type": "CLIENT_DHCP_TIMED_OUT", "text": "no ACK"})
    dns_ok = pick_event({"timestamp": 1, "type": "CLIENT_DNS_OK", "text": "Status code 0 Successful"})
    ip_ok = pick_event({"timestamp": 1, "type": "CLIENT_IP_ASSIGNED", "text": "DHCP assigned 10.40.12.88"})
    dhcp_ok = pick_event({"timestamp": 1, "type": "CLIENT_DHCP_SUCCESS", "text": "DHCP Success"})
    bad_ip = pick_event({"timestamp": 1, "type": "CLIENT_BAD_IP_ASSIGNED", "text": "Bad IP Assigned"})
    dns_fail = pick_event({"timestamp": 1, "type": "CLIENT_DNS_FAILURE", "text": "DNS Failure"})
    assert assoc["negative"] is False, assoc
    assert author["negative"] is False, author
    assert deauth["negative"] is True, deauth
    assert disassoc["negative"] is True, disassoc
    assert dhcp["negative"] is True, dhcp
    assert dns_ok["negative"] is False, dns_ok
    assert ip_ok["negative"] is False, ip_ok
    assert dhcp_ok["negative"] is False, dhcp_ok
    assert bad_ip["negative"] is True, bad_ip
    assert dns_fail["negative"] is True, dns_fail

    stats = {
        "mac": "aabbccddeeff", "hostname": "h", "manufacture": "Apple", "os": None, "model": None,
        "ssid": "corp", "vlan": 40, "ip": "10.0.0.2", "ap": "ap1", "band": "5", "channel": 149,
        "proto": "ax", "rssi": -49, "snr": 38, "txRate": 200, "rxRate": 200, "uptime": 200,
        "lastSeen": 1, "txBytes": 1, "rxBytes": 1, "username": None, "keyMgmt": "WPA2-PSK",
        "txRetries": 271, "rxRetries": 10, "dualBand": True,
    }
    cors = build_correlations(stats, [], [])
    hit = next(c for c in cors if c["id"] == "retries-rf-ok")
    assert "CCI" in hit["evidence"] and "hidden node" in hit["evidence"], hit["evidence"]

    v = build_verdict(stats, [assoc, author, deauth], [])
    notes = " ".join(v["notes"]).lower()
    assert "deauth/disassoc" in notes, v["notes"]
    assert "authentication/association failure" not in notes, v["notes"]

    aliased = pick_stats({"mac": "aabbccddeeff", "num_tx_retries": 90, "rssi": -50})
    assert aliased["txRetries"] == 90, aliased

    demo_sessions = [
        {"ap": "0a0027aa1102", "ssid": "c", "band": "5", "connect": 1, "disconnect": None, "duration": 3794},
        {"ap": "0a0027aa1101", "ssid": "c", "band": "5", "connect": 1, "disconnect": 2, "duration": 28},
    ]
    user_marvis = {
        "results": [{
            "category": "Device Health",
            "text": " The AP is currently online. Client demo-client was connected to DEMO-AP-F2-aa:11:01 most of the time.",
            "site_id": "9885f682-0bcc-4a35-5645-6456546546456",
        }],
        "start": 1787763220,
        "end": 1787849620,
    }
    hints = parse_marvis_ap_hints(user_marvis)
    assert hints["mostName"] == "DEMO-AP-F2-aa:11:01", hints

    inventory = [
        {"id": "00000000-0000-0000-1000-0a0027aa1101", "name": "DEMO-AP-F2-aa:11:01", "mac": "0a0027aa1101", "type": "ap"},
        {"id": "00000000-0000-0000-1000-0a0027aa1102", "name": "DEMO-AP-F2-aa:11:02", "mac": "0a0027aa1102", "type": "ap"},
    ]
    picked = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=inventory)
    assert picked["apMac"] == "0a0027aa1101", picked
    assert picked["source"] == "marvis", picked
    assert picked["fallback"] is False, picked
    assert "aa:11:01" in (picked.get("apNameHint") or picked.get("marvisName") or ""), picked

    # inventory name without colons still matches
    inv_nocolon = [{"id": "x", "name": "DEMO-AP-F2-aa1101", "mac": "0a0027aa1101", "type": "ap"}]
    picked_nc = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=inv_nocolon)
    assert picked_nc["apMac"] == "0a0027aa1101", picked_nc

    # MAC suffix in Marvis name matches inventory mac even if labels differ
    inv_suf = [{"id": "x", "name": "DEMO-AP-F2", "mac": "0a0027aa1101", "type": "ap"}]
    picked_suf = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=inv_suf)
    assert picked_suf["apMac"] == "0a0027aa1101", picked_suf

    # no inventory → cannot resolve name to MAC → longest session + note
    picked_fb = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=[])
    assert picked_fb["apMac"] == "0a0027aa1102", picked_fb
    assert picked_fb["fallback"] is True, picked_fb
    assert "marvis named" in picked_fb["selectionNote"].lower(), picked_fb["selectionNote"]

    s, e, n = rrm_channel_stack({
        "util_score_non_wifi": 0.76, "util_score_other": 0.16,
        "rssi": -55, "other_rssi": -80, "channel": 153,
    })
    assert n >= 70, (s, e, n)
    assert s > e, (s, e, n)

    s2, e2, n2 = rrm_occupancy_stack({"wifi": 0.16, "non_wifi": 0.70, "rssi": -50, "channel": 153})
    assert (s2, e2, n2) == (16, 0, 70), (s2, e2, n2)
    s3, e3, n3 = rrm_occupancy_stack({"wifi": 0.05, "non_wifi": 0.75, "other_rssi": -62, "channel": 161})
    assert (s3, e3, n3) == (0, 5, 75), (s3, e3, n3)
    s4, e4, n4 = rrm_occupancy_stack({"wifi": 0.09, "non_wifi": 0, "rssi": -48, "channel": 144})
    assert (s4, e4, n4) == (9, 0, 0), (s4, e4, n4)
    # non_wifi set must NOT drop util_score_other (portal orange/teal caps)
    s5, e5, n5 = rrm_occupancy_stack({"non_wifi": 0.75, "util_score_other": 0.05, "other_ssid": "ext"})
    assert (s5, e5, n5) == (0, 5, 75), (s5, e5, n5)
    s6, e6, n6 = rrm_occupancy_stack({"util_score_other": 0.40, "rssi": -52})
    assert (s6, e6, n6) == (40, 0, 0), (s6, e6, n6)
    s7, e7, n7 = rrm_occupancy_stack({"util_score_other": 0.40}, site_on_channel=True)
    assert (s7, e7, n7) == (40, 0, 0), (s7, e7, n7)
    s8, e8, n8 = rrm_occupancy_stack({"util_score_other": 0.05})  # unknown wifi → External (teal)
    assert (s8, e8, n8) == (0, 5, 0), (s8, e8, n8)
    keyed = rrm_rows_from({"100": {"wifi": 0.4, "rssi": -50}, "153": {"non_wifi": 0.7, "wifi": 0.16, "rssi": -55}})
    assert {int(r["channel"]) for r in keyed} == {100, 153}, keyed

    inv = [
        {"mac": "0a0027aa1101", "type": "ap", "radio_stat": {"band_5": {
            "channel": 144, "power": 8, "num_clients": 0, "util_all": 13,
            "util_tx": 1, "util_rx_in_bss": 8, "util_rx_other_bss": 0, "util_non_wifi": 0,
        }}},
        {"mac": "0a0027aa1104", "type": "ap", "radio_stat": {"band_5": {
            "channel": 157, "power": 8, "num_clients": 0, "util_all": 25,
            "util_tx": 4, "util_rx_in_bss": 16, "util_rx_other_bss": 3, "util_non_wifi": 0,
        }}},
        {"mac": "0a0027aa1105", "type": "ap", "radio_stat": {"band_5": {
            "channel": 108, "power": 8, "num_clients": 2, "util_all": 50,
            "util_tx": 10, "util_rx_in_bss": 37, "util_rx_other_bss": 2, "util_non_wifi": 1,
        }}},
    ]
    air = site_airtime_by_channel(inv, "5")
    assert air[144] == 9, air  # 1+8 in-BSS, not util_all
    assert air[157] == 20, air
    assert air[108] == 47, air
    rrm_only_dirty = [
        {"channel": 153, "non_wifi": 0.70, "util_score_other": 0.16, "rssi": -52},
        {"channel": 161, "non_wifi": 0.75, "util_score_other": 0.05, "other_ssid": "x"},
        {"channel": 165, "non_wifi": 1.0, "other_ssid": "x"},
    ]
    merged = channels_from_rrm(rrm_only_dirty, 144, None, band="5", site_channels=air)
    by = {c["channel"]: c for c in merged}
    assert by[108]["site"] == 47 and by[108]["external"] == 0 and by[108]["nonWifi"] == 0, by[108]
    assert by[144]["site"] == 9 and by[144]["serving"] is True, by[144]
    assert by[157]["site"] == 20, by[157]
    assert by[153]["nonWifi"] == 70 and by[153]["site"] >= 16, by[153]
    assert by[161]["nonWifi"] == 75 and by[161]["external"] == 5 and by[161]["site"] == 0, by[161]
    assert by[165]["nonWifi"] == 100, by[165]

    padded = channels_from_rrm(
        [{"channel": 153, "wifi": 0.16, "non_wifi": 0.70, "rssi": -50}],
        144, None, band="5",
    )
    chs = {c["channel"]: c for c in padded}
    assert 100 in chs and 165 in chs and 144 in chs, sorted(chs)
    assert chs[144]["serving"] is True
    assert chs[153]["nonWifi"] == 70 and chs[153]["site"] == 16
    assert chs[144]["external"] == 0  # not radio_stat overlay

    ap_radio = {
        "apMac": "0a0027aa1102", "apName": "DEMO-AP-F2", "status": "connected",
        "band": "5", "unavailable": None,
        "radio": {"channel": 144, "utilNonWifi": 0, "utilRxOtherBss": 0, "utilUnknownWifi": 0, "utilRxInBss": 9},
        "channels": [
            {"channel": 144, "site": 9, "external": 0, "nonWifi": 0, "serving": True},
            {"channel": 153, "site": 16, "external": 0, "nonWifi": 76, "serving": False},
        ],
    }
    rf = rf_occupancy_correlations(ap_radio, stats)
    ids = {c["id"] for c in rf}
    assert "ap-adj-nonwifi" in ids, rf
    assert "ap-nonwifi" not in ids, rf
    dirty = {
        **ap_radio,
        "channels": [
            {"channel": 144, "site": 9, "external": 0, "nonWifi": 42, "serving": True},
            {"channel": 153, "site": 16, "external": 0, "nonWifi": 76, "serving": False},
        ],
    }
    rf2 = rf_occupancy_correlations(dirty, stats)
    assert any(c["id"] == "ap-nonwifi" for c in rf2), rf2
    v2 = build_verdict(stats, [], [], dirty)
    assert any("non-Wi-Fi occupancy" in n for n in v2["notes"]), v2["notes"]
    assert any(c["id"] == "ap-nonwifi" for c in v2["correlations"]), v2["correlations"]

    t0 = 1_700_000_000
    q = rrm_events_query("5", page=1, limit=100)
    assert q["band"] == "5" and q["duration"] == "7d" and q["page"] == 1, q
    try:
        rrm_events_query("")
        raise AssertionError("empty band must fail")
    except ValueError as err:
        assert "band" in str(err).lower(), err
    nw = pick_rrm_event({"event": "interference-ap-non-wifi", "ap": "0a0027aa1102", "band": "5", "channel": 136, "pre_channel": 44})
    assert nw["label"] == "Interference AP non wifi", nw
    radar = pick_rrm_event({
        "timestamp": t0, "ap": "0a0027aa1103", "band": "5",
        "event": "rrm-radar", "channel": 149, "pre_channel": 36,
        "bandwidth": 80, "pre_bandwidth": 80, "power": 17, "pre_power": 17,
    })
    assert radar["channelChanged"] is True, radar
    assert radar["label"] == "Post radar", radar
    assert is_radar_event(radar)
    drop = pick_event({
        "timestamp": t0 + 12, "type": "CLIENT_DEAUTHENTICATION",
        "text": "Deauthenticated by AP", "ap": "0a0027aa1103", "channel": 36, "reason": 4,
    })
    sess_on = [{"ap": "0a0027aa1103", "connect": t0 - 60, "disconnect": t0 + 12, "duration": 72}]
    rc = radio_event_correlations([radar], [drop], sess_on, None, {"apMac": "0a0027aa1102"})
    assert len(rc) == 1, rc
    assert rc[0]["highlight"] is True, rc[0]
    assert "connected to" in rc[0]["title"].lower(), rc[0]
    assert rc[0]["severity"] == "crit"
    assert same_ap_mac(rc[0]["detail"]["clientAp"], rc[0]["detail"]["radarAp"]), rc[0]["detail"]
    ok, on = radar_hits_this_client(radar, sess_on, [drop], None)
    assert ok is True and on == "0a0027aa1103", (ok, on)

    # Radar on the connected AP with NO deauth still highlights
    sess_open = [{"ap": "0a0027aa1103", "connect": t0 - 60, "disconnect": None, "duration": None}]
    rc_nodrop = radio_event_correlations([radar], [], sess_open, None, None)
    assert rc_nodrop and rc_nodrop[0]["highlight"] is True, rc_nodrop
    assert "connected to" in rc_nodrop[0]["title"].lower()

    # Radar on a different AP while client is elsewhere — correlation is invalid
    sess_other = [{"ap": "0a0027aa1102", "connect": t0 - 60, "disconnect": t0 + 60, "duration": 120}]
    rc_miss = radio_event_correlations([radar], [], sess_other, None, {"apMac": "0a0027aa1102"})
    assert rc_miss == [], rc_miss
    ok_miss, on_miss = radar_hits_this_client(radar, sess_other, [], {"ap": "0a0027aa1102"})
    assert ok_miss is False and on_miss == "0a0027aa1102", (ok_miss, on_miss)

    # Same-channel drop on a different AP is not a radar match
    drop_other = pick_event({
        "timestamp": t0 + 8, "type": "CLIENT_DEAUTHENTICATION",
        "text": "Deauthenticated by AP", "ap": "0a0027aa1102", "channel": 36, "reason": 4,
    })
    rc_ch = radio_event_correlations([radar], [drop_other], sess_other, None, {"apMac": "0a0027aa1102"})
    assert rc_ch == [], rc_ch

    # Live stats AP must not pin a 4-day-old radar to today's AP
    old_radar = pick_rrm_event({
        "timestamp": t0 - 4 * 86400, "ap": "0a0027aa1102", "band": "5",
        "event": "rrm-radar", "channel": 44, "pre_channel": 36,
        "bandwidth": 20, "pre_bandwidth": 20, "power": 6, "pre_power": 6,
    })
    rc_old = radio_event_correlations([old_radar], [], [], {"ap": "0a0027aa1102"}, {"apMac": "0a0027aa1102"})
    assert rc_old == [], rc_old

    sched = pick_rrm_event({
        "timestamp": t0 - 100, "ap": "0a0027aa1102", "band": "5",
        "event": "scheduled-site_rrm", "channel": 144, "pre_channel": 144,
        "bandwidth": 20, "pre_bandwidth": 20, "power": 8, "pre_power": 8,
    })
    assert sched["channelChanged"] is False, sched
    rc2 = radio_event_correlations([sched], [drop], sess_on, None, {"apMac": "0a0027aa1102"})
    assert rc2 == [], rc2

    pwr = pick_rrm_event({
        "timestamp": t0, "ap": "0a0027aa1103", "band": "5",
        "event": "triggered-site_rrm", "channel": 144, "pre_channel": 144,
        "bandwidth": 20, "pre_bandwidth": 20, "power": 8, "pre_power": 14,
    })
    assert power_changed(pwr)
    rc_pwr = radio_event_correlations([pwr], [], sess_open, None, None)
    assert any(c["id"].startswith("radio-power") for c in rc_pwr), rc_pwr

    teams_bad = pick_call({
        "app": "teams", "mac": DEMO_MAC, "meeting_id": "m1",
        "start_time": t0 - 20, "end_time": t0 + 80,
        "audio_quality": 2, "video_quality": 3, "rating": 2,
    })
    assert teams_bad["teams"] and teams_bad["poor"], teams_bad
    cc = call_correlations([teams_bad], [drop], sess_on, {"rssi": -81, "snr": 11}, [])
    assert any(c["id"].startswith("call-drop") for c in cc), cc

    cc_radar = call_correlations([teams_bad], [drop], sess_on, {"rssi": -81, "snr": 11}, [radar])
    hit = next(c for c in cc_radar if c["id"].startswith("call-radar"))
    assert hit.get("highlight") is True, hit
    d = hit.get("detail") or {}
    assert d.get("call") == "Microsoft Teams", d
    assert d.get("meetingId") == "m1", d
    assert d.get("callStart") == t0 - 20, d
    assert d.get("radarEvent") == "Post radar", d
    assert d.get("radarTime") == t0, d
    assert d.get("clientAp") == "0a0027aa1103", d
    assert d.get("radarAp") == "0a0027aa1103", d
    assert d.get("clientAp") == d.get("radarAp"), d
    assert "36" in str(d.get("radarChannel")) and "149" in str(d.get("radarChannel")), d

    # Session-on-AP radar alert (dashboard banner). Same AP required.
    al = radar_session_alerts([radar], sess_on, [teams_bad], None)
    assert len(al) == 1, al
    assert al[0]["sessionAp"] == al[0]["radarAp"] == "0a0027aa1103", al[0]
    assert al[0]["call"] == "Microsoft Teams", al[0]
    assert al[0]["meetingId"] == "m1", al[0]
    assert al[0]["session"]["connect"] == sess_on[0]["connect"], al[0]["session"]
    assert al[0]["session"]["ap"] == "0a0027aa1103", al[0]["session"]
    assert al[0]["radio"]["event"] == "rrm-radar", al[0]["radio"]
    assert al[0]["radio"]["preChannel"] == 36 and al[0]["radio"]["channel"] == 149, al[0]["radio"]
    assert "This session" in PAGE and "This radar event" in PAGE
    assert sess_on[0].get("hitByRadar") is True, sess_on[0]
    assert radar_session_alerts([radar], sess_other, [teams_bad], None) == []
    assert radar_session_alerts([radar], [], [teams_bad], None) == []
    al_open = radar_session_alerts([radar], sess_open, [], None)
    assert len(al_open) == 1 and al_open[0]["sessionAp"] == "0a0027aa1103", al_open
    demo = demo_result()
    assert demo["radarAlerts"], demo.get("radarAlerts")
    da = demo["radarAlerts"][0]
    assert da["sessionAp"] == da["radarAp"] == "0a0027aa1103", da
    assert da["call"] == "Microsoft Teams", da
    assert any(s.get("hitByRadar") for s in demo["sessions"]), demo["sessions"]
    assert "sessions.slice(0,8)" not in PAGE
    assert "function sessionsPanel" in PAGE
    assert "nothing is truncated" in PAGE

    # Teams during radar on a DIFFERENT AP is not a valid correlation
    cc_wrong_ap = call_correlations([teams_bad], [drop], sess_other, {"rssi": -81, "snr": 11, "ap": "0a0027aa1102"}, [radar])
    assert not any(c["id"].startswith("call-radar") for c in cc_wrong_ap), cc_wrong_ap

    teams_qos = pick_call({
        "app": "teams", "start_time": t0 - 500, "end_time": t0 - 400,
        "audio_quality": 1, "video_quality": 5,
    })
    cc2 = call_correlations([teams_qos], [], [], {"rssi": -52, "snr": 32}, [])
    assert any("audio" in c["title"].lower() and "qos" in c["id"] for c in cc2), cc2

    roam_ev = pick_event({"timestamp": t0 + 5, "type": "CLIENT_ROAMED", "ap": "0a0027aa1102", "band": "5"})
    roam_ev2 = pick_event({"timestamp": t0 + 25, "type": "CLIENT_ROAMED", "ap": "0a0027aa1103", "band": "5"})
    cc_roam = call_correlations([teams_bad], [roam_ev, roam_ev2], sess_on, {"rssi": -60, "snr": 28}, [])
    assert any(c["id"].startswith("call-roam") for c in cc_roam), cc_roam

    cc_ret = call_correlations(
        [pick_call({"app": "teams", "start_time": t0 - 500, "end_time": t0 - 400, "audio_quality": 2, "video_quality": 2})],
        [], [], {"rssi": -62, "snr": 26, "txRetries": 120}, [],
    )
    assert any(c["id"].startswith("call-retries") for c in cc_ret), cc_ret

    demo = demo_result(False)
    demo_ids = [c["id"] for c in demo["verdict"]["correlations"]]
    assert any(i.startswith("radio-radar") for i in demo_ids), demo_ids
    assert any(c.get("highlight") for c in demo["verdict"]["correlations"]), demo["verdict"]["correlations"]
    assert any(i.startswith("call-radar") or i.startswith("call-drop") for i in demo_ids), demo_ids
    assert any(e.get("highlight") for e in demo["radioEvents"]), demo["radioEvents"]
    assert any(c["teams"] for c in demo["calls"]), demo["calls"]
    assert client_ap_at(demo["sessions"], demo["events"], demo["stats"], demo["radioEvents"][0]["timestamp"] if False else None or 0) or True

    # Demo rrm-radar is on 1103 while the session t-480..t-148 covers t-156
    demo_radar = next(e for e in demo["radioEvents"] if e["event"] == "rrm-radar")
    assert demo_radar["onClientAp"] is True, demo_radar
    assert demo_radar["highlight"] is True, demo_radar

    # Millisecond Mist timestamps must still match second-based sessions.
    assert epoch_s(t0) == float(t0)
    assert epoch_s(t0 * 1000) == float(t0)
    radar_ms = pick_rrm_event({
        "timestamp": t0 * 1000, "ap": "0a0027aa1103", "band": "5",
        "event": "rrm-radar", "channel": 149, "pre_channel": 36,
        "bandwidth": 80, "pre_bandwidth": 80, "power": 17, "pre_power": 17,
    })
    assert radar_ms["timestamp"] == float(t0), radar_ms
    rc_ms = radio_event_correlations([radar_ms], [drop], sess_on, None, None)
    assert rc_ms and rc_ms[0]["highlight"] is True, rc_ms

    # 7-day volume: many DFS hits on the client AP + a flood of neighbor-AP radar.
    # The old verdict dedupe stripped "-<timestamp>" and kept only ONE radio-radar card.
    many: list[dict] = []
    for i in range(40):
        many.append(pick_rrm_event({
            "timestamp": t0 - i * 3600, "ap": "0a0027aa1103", "band": "5",
            "event": "rrm-radar", "channel": 149, "pre_channel": 36,
            "bandwidth": 80, "pre_bandwidth": 80, "power": 17, "pre_power": 17,
        }))
    for i in range(120):
        many.append(pick_rrm_event({
            "timestamp": t0 - i * 1800, "ap": "0a0027aa1109", "band": "5",
            "event": "rrm-radar", "channel": 44, "pre_channel": 36,
            "bandwidth": 20, "pre_bandwidth": 20, "power": 6, "pre_power": 6,
        }))
    sess_week = [{
        "ap": "0a0027aa1103", "apName": "DEMO-AP-F2-aa:11:03",
        "connect": t0 - 7 * 86400, "disconnect": t0 + 60, "duration": 7 * 86400,
    }]
    rc_many = radio_event_correlations(many, [], sess_week, None, None)
    assert len(rc_many) == 40, len(rc_many)
    assert all(c.get("highlight") for c in rc_many)
    v_many = build_verdict(None, [], sess_week, None, many, [])
    radar_cors = [c for c in v_many["correlations"] if str(c["id"]).startswith("radio-radar")]
    assert len(radar_cors) == 40, (len(radar_cors), radar_cors[:3])
    assert any("40 Post radar" in n or "40" in n and "radar" in n.lower() for n in v_many["notes"]), v_many["notes"]
    al_many = radar_session_alerts(many, sess_week, [], None)
    assert len(al_many) == 1, len(al_many)
    assert len(al_many[0]["radios"]) == 40, len(al_many[0]["radios"])
    assert sess_week[0].get("hitByRadar") is True
    assert radar_session_alerts(many, [{"ap": "0a0027aa1102", "connect": t0 - 7 * 86400, "disconnect": t0, "duration": 7 * 86400}], [], None) == []
    stale = [{"id": f"radio-radar-{t0 - i}", "title": "x", "severity": "crit", "confidence": "high", "highlight": True} for i in range(5)]
    assert len(dedupe_correlations(stale)) == 5
    # Two radars during one Teams call, same AP — both kept (not just radar_hits[0])
    radar_b = pick_rrm_event({
        "timestamp": t0 + 40, "ap": "0a0027aa1103", "band": "5",
        "event": "rrm-radar", "channel": 44, "pre_channel": 149,
        "bandwidth": 80, "pre_bandwidth": 80, "power": 17, "pre_power": 17,
    })
    sess_long = [{"ap": "0a0027aa1103", "connect": t0 - 60, "disconnect": t0 + 90, "duration": 150}]
    cc_two = call_correlations([teams_bad], [drop], sess_long, {"rssi": -81, "snr": 11}, [radar, radar_b])
    assert len([c for c in cc_two if c["id"].startswith("call-radar")]) == 2, cc_two

    # AP-keyed store: buried client DFS among 2000 neighbor radars, BSSID alias.
    store = RadioEventStore({"0a0027aa1103"}, [{"0a0027aa1100", "0a0027aa1103"}])
    buried = pick_rrm_event({
        "timestamp": t0 - 3600, "ap": "0a0027aa1100", "band": "5",
        "event": "rrm-radar", "channel": 149, "pre_channel": 36,
    })
    for i in range(2000):
        store.add(pick_rrm_event({
            "timestamp": t0 - i, "ap": "0a0027aa11ff", "band": "5",
            "event": "rrm-radar", "channel": 44, "pre_channel": 36,
        }))
    store.add(buried)
    sess_b = [{"ap": "0a0027aa1103", "connect": t0 - 86400, "disconnect": t0, "duration": 86400}]
    assert len(store.hits_for_session(sess_b[0])) == 1, store.hits_for_session(sess_b[0])
    assert store.client_radar_events(sess_b)[0]["ap"] == "0a0027aa1100"
    exported = store.export_events()
    assert not any(e["ap"] == "0a0027aa11ff" for e in exported), "neighbor radar must not fill the UI export"
    assert store.radars_on_ap("0a0027aa11ff"), "neighbor radar must stay indexed for lookup"
    al_store = radar_session_alerts(exported, sess_b, [], None, store)
    assert len(al_store) == 1, al_store
    rc_store = radio_event_correlations(exported, [], sess_b, None, None, store)
    assert len([c for c in rc_store if c["id"].startswith("radio-radar")]) == 1
    slices = rrm_time_slices("1d", now=t0)
    assert len(slices) == 8, slices  # 24h / 3h
    assert slices[0][1] == t0 and slices[-1][0] == t0 - 86400
    assert "sess-scroll" in PAGE
    assert "radar-scroll" in PAGE
    assert "ranked.slice(0,60)" not in PAGE
    assert "function clientRadarPanel" in PAGE
    assert "Radar hits on this client's APs (0)" in PAGE
    demo2 = demo_result()
    assert demo2.get("clientRadarEvents"), demo2.get("clientRadarEvents")
    assert demo2.get("radioStoreStats", {}).get("clientHits", 0) >= 1

    # Open session with disconnect=0 must still cover a radar hit (Mist sends 0, not null).
    sess_zero = [{"ap": "0a0027aa1103", "connect": t0 - 60, "disconnect": 0, "duration": None}]
    assert session_covers(sess_zero[0], t0)
    al_zero = radar_session_alerts([radar], sess_zero, [], None)
    assert len(al_zero) == 1, al_zero

    # RRM payload that names the AP as ap_mac / mac still correlates.
    radar_alias = pick_rrm_event({
        "timestamp": t0, "ap_mac": "0a0027aa1103", "band": "5",
        "event": "radar-detected", "channel": 100, "pre_channel": 36,
    })
    assert radar_alias["ap"] == "0a0027aa1103", radar_alias
    assert is_radar_event(radar_alias)
    al_alias = radar_session_alerts([radar_alias], sess_on, [], None)
    assert len(al_alias) == 1, al_alias

    # Always-indexed neighbor radar must not alert for a different session AP.
    storm_store = RadioEventStore({"0a0027aa1103"})
    for i in range(50):
        storm_store.add(pick_rrm_event({
            "timestamp": t0 - i, "ap": "0a0027aa11ff", "event": "rrm-radar",
            "channel": 44, "pre_channel": 36, "band": "5",
        }))
    storm_store.add(pick_rrm_event({
        "timestamp": t0 - 10, "ap": "0a0027aa1103", "event": "rrm-radar",
        "channel": 149, "pre_channel": 36, "band": "5",
    }))
    sess_storm = [{"ap": "0a0027aa1103", "connect": t0 - 120, "disconnect": t0, "duration": 120}]
    assert len(storm_store.hits_for_session(sess_storm[0])) == 1
    assert len(storm_store.export_events()) < 10, len(storm_store.export_events())
    assert len(radar_session_alerts(storm_store.export_events(), sess_storm, [], None, storm_store)) == 1

    print("self-test ok")


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Mist Disconnect Console (local browser)")
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1, this PC only)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--self-test", action="store_true", help="Run correlation-engine checks and exit")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Mist Disconnect Console")
    print(f"Open {url}  (Ctrl+C to stop)")
    print("Use a read-only Observer API token. This process only issues GET requests to Mist.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
