#!/usr/bin/env python3
# Mist Disconnect Console — local browser app (Windows / macOS / Linux)
#
# Exact dashboard: Observer-token gate, site/MAC RCA, correlations, live poll,
# and Radio Management-style occupancy (Site APs / External APs / Non-Wi-Fi)
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
DEMO_MAC = "a483e7129c4b"
WINDOW_DHCP_S = 120
WINDOW_HANDSHAKE_S = 45
WINDOW_CLUSTER_S = 300
PINGPONG_MIN = 4

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
    "DEAUTH", "DISASSOC", "FAIL", "DENIED", "TIMEOUT", "STUCK",
    "DISCONNECT", "DHCP", "DNS", "ARP", "BLOCKED",
)

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
    hay = f"{typ} {text}".upper()
    if ("SUCCESS" in hay or "OK" in hay or "JOINED" in hay) and "FAIL" not in hay:
        return False
    # AUTH is not a keyword: ASSOCIATION / AUTHORIZATION contain it and would
    # mark every successful join as a failure.
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
        "lastSeen": num(raw.get("last_seen", raw.get("timestamp"))),
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
        "timestamp": num(raw.get("timestamp")) or 0,
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
    return {
        "ap": str(raw.get("ap") or ""),
        "ssid": str(raw.get("ssid") or ""),
        "band": str(raw.get("band") or ""),
        "connect": num(raw.get("connect")),
        "disconnect": num(raw.get("disconnect")),
        "duration": num(raw.get("duration")),
    }


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
    seen: set[str] = set()
    uniq = []
    for c in out:
        key = re.sub(r"-\d+$", "", c["id"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


def build_verdict(stats: dict | None, events: list, sessions: list, ap_radio: dict | None = None) -> dict:
    notes: list[str] = []
    score = 100
    cors = build_correlations(stats, events, sessions)
    cors.extend(rf_occupancy_correlations(ap_radio, stats))
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
    rank = {"crit": 0, "warn": 1, "info": 2}
    conf = {"high": 0, "medium": 1, "low": 2}
    cors.sort(key=lambda c: (rank.get(c["severity"], 9), conf.get(c["confidence"], 9)))
    seen_c: set[str] = set()
    uniq_c: list[dict] = []
    for c in cors:
        key = re.sub(r"-\d+$", "", c["id"])
        if key in seen_c:
            continue
        seen_c.add(key)
        uniq_c.append(c)
    cors = uniq_c
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


def mist_get(host: str, token: str, path: str, params: dict | None = None) -> Any:
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
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
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


def diagnose_client(token: str, host: str, org_id: str, site_id: str, site_name: str, mac: str, duration: str) -> dict:
    mac = normalize_mac(mac)
    colon = format_mac(mac)
    paths = {
        "stats": (f"/sites/{site_id}/stats/clients/{mac}", None),
        "search": (f"/sites/{site_id}/clients/search", {"mac": mac, "duration": duration, "limit": 20}),
        "events": (f"/sites/{site_id}/clients/{mac}/events", {"duration": duration, "limit": 100}),
        "sessions": (f"/sites/{site_id}/clients/sessions/search", {"mac": mac, "duration": duration, "limit": 50}),
        "marvis": (f"/orgs/{org_id}/troubleshoot", {"mac": colon, "site_id": site_id}),
        "aps": (f"/sites/{site_id}/devices", {"type": "ap"}),
        "devices": (f"/sites/{site_id}/stats/devices", {"type": "ap"}),
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
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    sessions = [pick_session(r) for r in as_array(got.get("sessions"))]
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
    ap_radio: dict
    try:
        ap_radio = fetch_ap_radio(
            token, host, site_id, stats, events, sessions, marvis_raw if marvis_raw is not None else marvis_text,
            inventory=inventory,
        )
    except Exception as e:  # noqa: BLE001
        ap_radio = {"unavailable": str(e), "channels": [], "radio": None, "apMac": hex_mac((stats or {}).get("ap"))}
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
        "verdict": build_verdict(stats, events, sessions, ap_radio),
        "fetchedAt": int(time.time() * 1000),
    }


def demo_result(jitter: bool = False) -> dict:
    t = int(time.time())
    j = int((__import__("random").random() - 0.5) * 6) if jitter else 0
    stats = {
        "mac": DEMO_MAC,
        "hostname": "VALERIE-MBP",
        "manufacture": "Apple",
        "os": "macOS 15.5",
        "model": "MacBookPro18,3",
        "ssid": "CORP-WIFI",
        "vlan": 40,
        "ip": "10.40.12.88",
        "ap": "5c5b350eb31b",
        "band": "5",
        "channel": 149,
        "proto": "ax",
        "rssi": -81 + j,
        "snr": max(6, 11 + j // 2),
        "txRate": 58,
        "rxRate": 48,
        "uptime": 214,
        "lastSeen": t - 12,
        "txBytes": 1843200,
        "rxBytes": 9216000,
        "username": "vcowan",
        "keyMgmt": "WPA2-PSK",
        "txRetries": 214,
        "rxRetries": 88,
        "dualBand": True,
    }
    events = [
        pick_event({"timestamp": t - 40, "type": "CLIENT_DNS_OK", "text": "Status code 0 Successful", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 90, "type": "CLIENT_DHCP_TIMED_OUT", "text": "DORA incomplete — no ACK", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 140, "type": "CLIENT_ASSOCIATION", "text": "Associated", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 148, "type": "CLIENT_DEAUTHENTICATION", "text": "Deauthenticated by AP", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 4}),
        pick_event({"timestamp": t - 420, "type": "CLIENT_DEAUTHENTICATION", "text": "4-way handshake timeout", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 15}),
        pick_event({"timestamp": t - 900, "type": "CLIENT_ROAMED", "text": "Roamed from 5c5b350a4412", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 1800, "type": "CLIENT_AUTHORIZATION", "text": "Authorized", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36}),
        pick_event({"timestamp": t - 3600, "type": "CLIENT_DISASSOCIATION", "text": "STA leaving BSS", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "2.4", "channel": 11, "reason": 8}),
    ]
    sessions = [
        {"ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "connect": t - 214, "disconnect": None, "duration": 214},
        {"ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "connect": t - 480, "disconnect": t - 148, "duration": 28},
        {"ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "connect": t - 900, "disconnect": t - 840, "duration": 44},
        {"ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "connect": t - 7200, "disconnect": t - 3600, "duration": 3580},
    ]
    marvis = {
        "results": [
            {
                "category": "Device Health",
                "text": " The AP is currently online. Client VALERIE-MBP was connected to MISS688-AP-F1-eb:31:1b most of the time.",
                "site_id": "demo-site",
            },
            {
                "category": "Wireless connectivity",
                "text": "Weak RSSI and handshake timeouts on AP 5c5b350a4412. Client repeatedly deauthenticates then reassociates.",
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
        "apMac": "5c5b350eb31b",
        "apName": "MISS688-AP-F1-eb:31:1b",
        "deviceId": mist_device_id("5c5b350eb31b"),
        "status": "connected",
        "band": "5",
        "source": "marvis",
        "dwellSeconds": 3794,
        "dwellShare": 0.98,
        "marvisMentioned": True,
        "marvisName": "MISS688-AP-F1-eb:31:1b",
        "selectionNote": "Marvis named MISS688-AP-F1-eb:31:1b as the AP this client used most of the time. Chart is that radio (5c:5b:35:0e:b3:1b).",
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
    return {
        "demo": True,
        "host": DEFAULT_HOST,
        "orgId": "demo-org",
        "siteId": "demo-site",
        "siteName": "Barrie HQ — Floor 2",
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
        "verdict": build_verdict(stats, events, sessions, ap_radio),
        "fetchedAt": int(time.time() * 1000),
        "email": "demo@local",
        "orgs": [{"id": "demo-org", "name": "Interconnected Systems (sample)"}],
        "sites": [{"id": "demo-site", "name": "Barrie HQ — Floor 2"}],
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
dl { display:grid; grid-template-columns: 7rem minmax(0,1fr); gap:.4rem .75rem; margin: .7rem 0 0; font-size:14px; }
dt { color:var(--subtle); } dd { margin:0; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:var(--surface-2); padding:.75rem; border-radius:10px; font-size:12px; }
.alert { border:1px solid color-mix(in oklab,var(--crit) 40%, var(--border)); color:var(--crit); padding:.75rem 1rem; border-radius:12px; margin-bottom:1rem; }
.hidden { display:none !important; }
.legend { display:flex; flex-wrap:wrap; gap:.75rem 1.1rem; font-size:12px; color:var(--muted); margin:.4rem 0 .8rem; }
.swatch { width:10px; height:10px; border-radius:2px; display:inline-block; margin-right:.35rem; vertical-align:middle; }
.ap-table { width:100%; border-collapse:collapse; font-size:13px; }
.ap-table th { text-align:left; color:var(--subtle); font-weight:500; padding:.4rem .5rem .5rem 0; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
.ap-table td { padding:.45rem .5rem .45rem 0; border-top:1px solid var(--border); }
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
    else res = await api("/api/diagnose", {token:state.token, host:state.host, orgId:state.orgId, siteId:state.siteId, siteName:(state.sites.find(s=>s.id===state.siteId)||{}).name||"", mac:state.mac||state.result?.mac, duration:state.duration});
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
    <p class="subtle" style="font-size:12px">Live mode re-queries client stats/events and the dominant AP's radio occupancy. Auto-pauses on Mist 429. 3s is aggressive.</p>
    <div class="card ${r.verdict.label==="Critical"?"pulse-c":""}">
      <div class="${vt}" style="font-size:1.15rem;font-weight:650">${esc(r.verdict.label)} · score ${r.verdict.score}</div>
      <p>${esc(r.verdict.primaryCause)}</p>
      <ul class="plain muted">${r.verdict.notes.map(n=>`<li>— ${esc(n)}</li>`).join("")}</ul>
    </div>
    <div class="card">
      <h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Correlated causes</h2>
      ${!cors.length?'<p class="muted">No multi-signal pattern in this window.</p>':cors.map(c=>`
        <div class="ev" style="border-color:color-mix(in oklab, var(--${c.severity==="info"?"border":c.severity}) 40%, var(--border))">
          <div class="row"><strong class="${c.severity==="crit"?"crit":c.severity==="warn"?"warn":"muted"}">${esc(c.title)}</strong>
          <span class="subtle" style="font-size:11px;text-transform:uppercase">${esc(c.confidence)} · ${esc(c.severity)}</span></div>
          <p class="muted" style="margin:.4rem 0 0">${esc(c.evidence)}</p>
        </div>`).join("")}
    </div>
    ${occPanel(r.apRadio)}
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
    <div class="grid2">
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
      <div class="card"><h2 class="subtle" style="margin:0;font-size:13px;text-transform:uppercase">Sessions</h2>
        ${!(r.sessions||[]).length?'<p class="muted">No session records in this window.</p>':`<div>${r.sessions.slice(0,8).map(sess=>`
          <div style="padding:.55rem 0;border-bottom:1px solid var(--border)">
            <div class="row"><span class="mono subtle">${esc(sess.ap||"AP —")}</span>
            <span class="mono ${sess.duration!=null&&sess.duration<60?"crit":""}">${esc(fmtDur(sess.duration))}</span></div>
            <div class="subtle" style="font-size:12px">${esc(sess.ssid||"")} · ${esc(sess.band||"band —")} · ${esc(fmtTime(sess.connect))}${sess.disconnect?" → "+fmtTime(sess.disconnect):" (open)"}</div>
          </div>`).join("")}</div>`}
      </div>
    </div>
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
    dhcp = pick_event({"timestamp": 1, "type": "CLIENT_DHCP_TIMED_OUT", "text": "no ACK"})
    dns_ok = pick_event({"timestamp": 1, "type": "CLIENT_DNS_OK", "text": "Status code 0 Successful"})
    assert assoc["negative"] is False, assoc
    assert author["negative"] is False, author
    assert deauth["negative"] is True, deauth
    assert dhcp["negative"] is True, dhcp
    assert dns_ok["negative"] is False, dns_ok

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
        {"ap": "5c5b350eb31b", "ssid": "c", "band": "5", "connect": 1, "disconnect": None, "duration": 3794},
        {"ap": "a8f7d9f096f0", "ssid": "c", "band": "5", "connect": 1, "disconnect": 2, "duration": 28},
    ]
    user_marvis = {
        "results": [{
            "category": "Device Health",
            "text": " The AP is currently online. Client serv_tsc_wifi was connected to MISS688-AP-F1-f0:96:f0 most of the time.",
            "site_id": "9885f682-0bcc-4a35-5645-6456546546456",
        }],
        "start": 1787763220,
        "end": 1787849620,
    }
    hints = parse_marvis_ap_hints(user_marvis)
    assert hints["mostName"] == "MISS688-AP-F1-f0:96:f0", hints

    inventory = [
        {"id": "00000000-0000-0000-1000-a8f7d9f096f0", "name": "MISS688-AP-F1-f0:96:f0", "mac": "a8f7d9f096f0", "type": "ap"},
        {"id": "00000000-0000-0000-1000-5c5b350eb31b", "name": "MISS688-AP-F1-eb:31:1b", "mac": "5c5b350eb31b", "type": "ap"},
    ]
    picked = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=inventory)
    assert picked["apMac"] == "a8f7d9f096f0", picked
    assert picked["source"] == "marvis", picked
    assert picked["fallback"] is False, picked
    assert "f0:96:f0" in (picked.get("apNameHint") or picked.get("marvisName") or ""), picked

    # inventory name without colons still matches
    inv_nocolon = [{"id": "x", "name": "MISS688-AP-F1-f096f0", "mac": "a8f7d9f096f0", "type": "ap"}]
    picked_nc = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=inv_nocolon)
    assert picked_nc["apMac"] == "a8f7d9f096f0", picked_nc

    # MAC suffix in Marvis name matches inventory mac even if labels differ
    inv_suf = [{"id": "x", "name": "MISS688-AP-F1", "mac": "a8f7d9f096f0", "type": "ap"}]
    picked_suf = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=inv_suf)
    assert picked_suf["apMac"] == "a8f7d9f096f0", picked_suf

    # no inventory → cannot resolve name to MAC → longest session + note
    picked_fb = pick_dominant_ap(demo_sessions, stats, [], user_marvis, inventory=[])
    assert picked_fb["apMac"] == "5c5b350eb31b", picked_fb
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
        {"mac": "a8f7d9f096f0", "type": "ap", "radio_stat": {"band_5": {
            "channel": 144, "power": 8, "num_clients": 0, "util_all": 13,
            "util_tx": 1, "util_rx_in_bss": 8, "util_rx_other_bss": 0, "util_non_wifi": 0,
        }}},
        {"mac": "a8f7d9f06dce", "type": "ap", "radio_stat": {"band_5": {
            "channel": 157, "power": 8, "num_clients": 0, "util_all": 25,
            "util_tx": 4, "util_rx_in_bss": 16, "util_rx_other_bss": 3, "util_non_wifi": 0,
        }}},
        {"mac": "a8f7d9f06fae", "type": "ap", "radio_stat": {"band_5": {
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
        "apMac": "5c5b350eb31b", "apName": "MISS688", "status": "connected",
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
