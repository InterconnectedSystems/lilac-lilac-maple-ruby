#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Juniper Mist — Client Disconnect Troubleshooter
Windows-compatible CLI dashboard (same RCA as the web console).

Default API host: api.gc2.mist.com

Install (Command Prompt or PowerShell):
    pip install requests colorama
    python mist_client_troubleshoot.py

Optional:
    python mist_client_troubleshoot.py --demo
    set MIST_TOKEN=your_token
    python mist_client_troubleshoot.py
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    sys.stderr.write("Missing dependency. Run:\n    pip install requests colorama\n")
    sys.exit(1)

try:
    from colorama import Fore, Style, init as colorama_init

    colorama_init(autoreset=False, convert=True, strip=False)
except ImportError:

    class _Empty:
        def __getattr__(self, _name: str) -> str:
            return ""

    Fore = Style = _Empty()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Windows console: UTF-8 + ANSI (colors / blink)
# ---------------------------------------------------------------------------
def _enable_windows_console() -> None:
    if sys.platform != "win32":
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # VT processing
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        os.system("")  # last-ditch ANSI enable on Win10+


_enable_windows_console()

BLINK = "\033[5m"
RESET = Style.RESET_ALL if hasattr(Style, "RESET_ALL") else "\033[0m"

ALLOWED_HOSTS = (
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
DEFAULT_HOST = "api.gc2.mist.com"
TIMEOUT = 25
EVENT_LIMIT = 100

RSSI_GOOD, RSSI_WARN = -65, -75
SNR_GOOD, SNR_WARN = 25, 15

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

NEGATIVE_KW = (
    "DEAUTH",
    "DISASSOC",
    "FAIL",
    "DENIED",
    "TIMEOUT",
    "STUCK",
    "DISCONNECT",
    "DHCP",
    "DNS",
    "ARP",
    "AUTH",
    "BLOCKED",
)


class MistError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize_mac(mac: str) -> str:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(cleaned) != 12:
        raise ValueError("MAC must be 12 hex digits (colons/dashes optional).")
    return cleaned.lower()


def format_mac(mac: str) -> str:
    n = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if len(n) != 12:
        return mac
    return ":".join(n[i : i + 2] for i in range(0, 12, 2))


def to_num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v == v:  # not NaN
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            return float(v)
        except ValueError:
            return None
    return None


def pretty_ts(ts: Any) -> str:
    n = to_num(ts)
    if n is None:
        return "—"
    if n > 1e12:
        n = n / 1000.0
    try:
        return datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(ts)


def fmt_duration(sec: Any) -> str:
    n = to_num(sec)
    if n is None:
        return "—"
    n = int(n)
    if n < 60:
        return f"{n}s"
    if n < 3600:
        return f"{n // 60}m {n % 60}s"
    return f"{n // 3600}h {(n % 3600) // 60}m"


def fmt_bytes(n: Any) -> str:
    v = to_num(n)
    if v is None:
        return "—"
    if v < 1024:
        return f"{int(v)} B"
    if v < 1024 * 1024:
        return f"{v / 1024:.1f} KB"
    if v < 1024 * 1024 * 1024:
        return f"{v / 1024 / 1024:.1f} MB"
    return f"{v / 1024 / 1024 / 1024:.2f} GB"


def describe_reason(code: Any) -> str | None:
    if code is None or code == "":
        return None
    try:
        n = int(code)
    except (TypeError, ValueError):
        return str(code)
    meaning = REASON_CODES.get(n)
    return f"{n} — {meaning}" if meaning else str(n)


def is_negative(etype: str, text: str) -> bool:
    hay = f"{etype} {text}".upper()
    if ("SUCCESS" in hay or "OK" in hay or "JOINED" in hay) and "FAIL" not in hay:
        return False
    return any(k in hay for k in NEGATIVE_KW)


def rssi_band(rssi: Any) -> str:
    v = to_num(rssi)
    if v is None:
        return "unknown"
    if v < RSSI_WARN:
        return "crit"
    if v < RSSI_GOOD:
        return "warn"
    return "good"


def snr_band(snr: Any) -> str:
    v = to_num(snr)
    if v is None:
        return "unknown"
    if v < SNR_WARN:
        return "crit"
    if v < SNR_GOOD:
        return "warn"
    return "good"


def paint(band: str, text: str, blink: bool = False) -> str:
    if band == "crit":
        body = f"{Fore.RED}{Style.BRIGHT}{text}{RESET}"
        return f"{BLINK}{body}{RESET}" if blink else body
    if band == "warn":
        return f"{Fore.YELLOW}{Style.BRIGHT}{text}{RESET}"
    if band == "good":
        return f"{Fore.GREEN}{text}{RESET}"
    return text


def rule(ch: str = "=", width: int = 74) -> str:
    return f"{Fore.CYAN}{ch * width}{RESET}"


def heading(title: str) -> None:
    print()
    print(f"{Fore.MAGENTA}{Style.BRIGHT}  {title}{RESET}")
    print(f"{Fore.MAGENTA}  {'-' * len(title)}{RESET}")


def kv(key: str, value: Any) -> None:
    print(f"  {key:<18} {value}")


def menu(items: list[tuple[str, Any]], prompt: str) -> Any:
    print()
    for i, (label, _) in enumerate(items, 1):
        print(f"  {Fore.CYAN}{i:3d}.{RESET} {label}")
    print()
    while True:
        choice = input(f"{prompt} [1-{len(items)}] (q=quit): ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            sys.exit(0)
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return items[idx][1]
        except ValueError:
            pass
        print(f"{Fore.YELLOW}Invalid choice.{RESET}")


def results_of(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results", [])
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
        if payload.get("mac"):
            return [payload]
    return []


# ---------------------------------------------------------------------------
# Classification (mirrors the web console)
# ---------------------------------------------------------------------------
def pick_stats(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "mac": str(raw.get("mac") or ""),
        "hostname": raw.get("hostname") or raw.get("device"),
        "manufacture": raw.get("manufacture") or raw.get("client_manufacture"),
        "os": raw.get("os"),
        "model": raw.get("model"),
        "ssid": raw.get("ssid"),
        "vlan": raw.get("vlan_id") if raw.get("vlan_id") is not None else raw.get("vlan"),
        "ip": raw.get("ip") or raw.get("ip6"),
        "ap": raw.get("ap") or raw.get("ap_mac"),
        "band": None if raw.get("band") is None else str(raw.get("band")),
        "channel": raw.get("channel"),
        "proto": raw.get("proto") or raw.get("protocol"),
        "rssi": to_num(raw.get("rssi", raw.get("rssi_dbm"))),
        "snr": to_num(raw.get("snr", raw.get("snr_db"))),
        "tx_rate": to_num(raw.get("tx_rate")),
        "rx_rate": to_num(raw.get("rx_rate")),
        "uptime": to_num(raw.get("uptime")),
        "last_seen": to_num(raw.get("last_seen", raw.get("timestamp"))),
        "tx_bytes": to_num(raw.get("tx_bytes")),
        "rx_bytes": to_num(raw.get("rx_bytes")),
        "username": raw.get("username"),
        "key_mgmt": raw.get("key_mgmt"),
    }


def pick_event(raw: dict[str, Any]) -> dict[str, Any]:
    etype = str(raw.get("type") or raw.get("type_code") or "unknown")
    text = str(raw.get("text") or "")
    return {
        "timestamp": to_num(raw.get("timestamp")) or 0,
        "type": etype,
        "text": text,
        "ap": str(raw.get("ap") or ""),
        "ssid": str(raw.get("ssid") or ""),
        "band": str(raw.get("band") or ""),
        "channel": raw.get("channel"),
        "reason": raw.get("reason_code", raw.get("reason")),
        "negative": is_negative(etype, text),
    }


def pick_session(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "ap": str(raw.get("ap") or ""),
        "ssid": str(raw.get("ssid") or ""),
        "band": str(raw.get("band") or ""),
        "connect": to_num(raw.get("connect")),
        "disconnect": to_num(raw.get("disconnect")),
        "duration": to_num(raw.get("duration")),
    }


def build_verdict(
    stats: dict[str, Any] | None,
    events: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    notes: list[str] = []
    score = 100
    rssi = stats.get("rssi") if stats else None
    snr = stats.get("snr") if stats else None
    rb = rssi_band(rssi)
    sb = snr_band(snr)

    if rb == "crit":
        score -= 25
        notes.append(f"RSSI {rssi} dBm is critically weak — coverage or obstruction.")
    elif rb == "warn":
        score -= 12
        notes.append(f"RSSI {rssi} dBm is marginal (target >= -65 dBm).")

    if sb == "crit":
        score -= 20
        notes.append(f"SNR {snr} dB is critically low — noise or interference likely.")
    elif sb == "warn":
        score -= 10
        notes.append(f"SNR {snr} dB is only fair (target >= 25 dB).")

    deauth = [e for e in events if re.search(r"DEAUTH|DISASSOC", e["type"], re.I)]
    dhcp = [e for e in events if re.search(r"DHCP", e["type"], re.I) and e["negative"]]
    auth = [e for e in events if re.search(r"AUTH|ASSOC", e["type"], re.I) and e["negative"]]
    roam = [e for e in events if re.search(r"ROAM", e["type"], re.I)]

    if deauth:
        score -= min(30, len(deauth) * 6)
        reasons = []
        seen: set[str] = set()
        for e in deauth:
            d = describe_reason(e.get("reason"))
            if d and d not in seen:
                seen.add(d)
                reasons.append(d)
        extra = f": {'; '.join(reasons)}" if reasons else ""
        notes.append(f"{len(deauth)} deauth/disassoc event(s){extra}.")
    if dhcp:
        score -= 15
        notes.append(f"{len(dhcp)} DHCP failure(s) after association — L3 / gateway.")
    if auth:
        score -= 15
        notes.append(f"{len(auth)} authentication/association failure(s).")
    if len(roam) >= 4:
        score -= 8
        notes.append(f"{len(roam)} roam events in the window — sticky client or coverage holes.")

    short = [s for s in sessions if s["duration"] is not None and 0 < s["duration"] < 60]
    if len(short) >= 3:
        score -= 10
        notes.append(f"{len(short)} sessions lasted under 60s — unstable association.")

    score = max(0, min(100, score))
    label = "Healthy" if score >= 80 else "Degraded" if score >= 50 else "Critical"

    primary = "No dominant failure signature — review the timeline."
    if rb == "crit" or sb == "crit":
        primary = "RF: weak signal or high noise"
    elif auth:
        primary = "Authentication / association failure"
    elif dhcp:
        primary = "DHCP / IP services after join"
    elif any(str(e.get("reason")) == "4" or re.search(r"inactiv", str(e.get("text") or ""), re.I) for e in deauth):
        primary = "Idle timeout / inactivity deauth"
    elif any(str(e.get("reason")) == "15" for e in deauth):
        primary = "4-way handshake timeout (PSK/EAP)"
    elif len(roam) >= 4:
        primary = "Excessive roaming"
    elif any(str(e.get("reason")) in {"3", "8"} for e in deauth):
        primary = "Client left the BSS (often user-initiated)"
    elif deauth:
        primary = "Repeated disconnects — see reason codes"

    if not notes:
        notes.append("RF metrics in range and no clustered failure events.")

    return {"score": score, "label": label, "primaryCause": primary, "notes": notes}


# ---------------------------------------------------------------------------
# Mist API
# ---------------------------------------------------------------------------
class MistClient:
    def __init__(self, token: str, host: str = DEFAULT_HOST) -> None:
        if host not in ALLOWED_HOSTS:
            raise MistError(f"Unknown Mist host: {host}")
        token = re.sub(r"^token\s+", "", token.strip(), flags=re.I)
        if len(token) < 8:
            raise MistError("API token looks empty.")
        self.host = host
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Accept": "application/json",
            }
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"https://{self.host}/api/v1{path}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        try:
            r = self.session.get(url, timeout=TIMEOUT)
        except requests.Timeout as exc:
            raise MistError("Mist API timed out after 25s.") from exc
        except requests.RequestException as exc:
            raise MistError(f"Request failed: {exc}") from exc

        if r.status_code == 204 or not r.content:
            return None
        if r.status_code == 401:
            raise MistError("Token rejected (401). Check region and token.")
        if r.status_code == 403:
            raise MistError("Token lacks permission for this org/site (403).")
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            raise MistError("Mist rate limit (429). Wait a minute and retry.")
        if not r.ok:
            raise MistError(f"Mist API {r.status_code}: {r.text[:200]}")
        return r.json()


def pick_orgs(self_info: dict[str, Any]) -> list[tuple[str, str]]:
    orgs: dict[str, str] = {}
    for p in self_info.get("privileges") or []:
        if isinstance(p, dict) and p.get("scope") == "org" and p.get("org_id"):
            orgs[str(p["org_id"])] = str(p.get("name") or p["org_id"])
    oid = self_info.get("org_id")
    if oid and str(oid) not in orgs:
        orgs[str(oid)] = str(self_info.get("name") or oid)
    if not orgs:
        raise MistError("No organization privileges on this token.")
    return [(name, oid) for oid, name in orgs.items()]


# ---------------------------------------------------------------------------
# Demo (same sample as the web console)
# ---------------------------------------------------------------------------
def build_demo() -> dict[str, Any]:
    t = int(time.time())
    stats = {
        "mac": "a483e7129c4b",
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
        "rssi": -81.0,
        "snr": 11.0,
        "tx_rate": 58.0,
        "rx_rate": 48.0,
        "uptime": 214.0,
        "last_seen": float(t - 12),
        "tx_bytes": 1843200.0,
        "rx_bytes": 9216000.0,
        "username": "vcowan",
        "key_mgmt": "WPA2-PSK",
    }
    events = [
        pick_event({"timestamp": t - 40, "type": "CLIENT_DNS_OK", "text": "Status code 0 Successful", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 90, "type": "CLIENT_DHCP_TIMED_OUT", "text": "DORA incomplete — no ACK", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 140, "type": "CLIENT_ASSOCIATION", "text": "Associated", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 148, "type": "CLIENT_DEAUTHENTICATION", "text": "Deauthenticated by AP", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 4}),
        pick_event({"timestamp": t - 420, "type": "CLIENT_DEAUTHENTICATION", "text": "4-way handshake timeout", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 15}),
        pick_event({"timestamp": t - 900, "type": "CLIENT_ROAMED", "text": "Roamed from 5c5b350a4412", "ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "channel": 149}),
        pick_event({"timestamp": t - 1800, "type": "CLIENT_AUTHORIZATION", "text": "Authorized", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36}),
        pick_event({"timestamp": t - 3600, "type": "CLIENT_DISASSOCIATION", "text": "STA leaving BSS", "ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "channel": 36, "reason": 8}),
    ]
    sessions = [
        {"ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "connect": t - 214, "disconnect": None, "duration": 214.0},
        {"ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "connect": t - 480, "disconnect": t - 148, "duration": 28.0},
        {"ap": "5c5b350a4412", "ssid": "CORP-WIFI", "band": "5", "connect": t - 900, "disconnect": t - 840, "duration": 44.0},
        {"ap": "5c5b350eb31b", "ssid": "CORP-WIFI", "band": "5", "connect": t - 7200, "disconnect": t - 3600, "duration": 3580.0},
    ]
    marvis = {
        "category": "Wireless connectivity",
        "reason": "Weak RSSI and handshake timeouts on AP 5c5b350a4412",
        "description": "Client repeatedly deauthenticates (reason 4 inactivity, reason 15 4-way timeout) then reassociates on a farther AP with RSSI -81 dBm and SNR 11 dB.",
        "recommendation": "Check AP 5c5b350a4412 radio / channel 36, verify PSK, and add coverage toward the client's last location. DHCP timeouts after rejoin suggest the client is also struggling L3 on the new AP.",
    }
    return {
        "demo": True,
        "host": DEFAULT_HOST,
        "site_name": "Barrie HQ — Floor 2",
        "mac": "a483e7129c4b",
        "duration": "1d",
        "stats": stats,
        "events": events,
        "sessions": sessions,
        "marvis": marvis,
        "verdict": build_verdict(stats, events, sessions),
    }


# ---------------------------------------------------------------------------
# Diagnose + render
# ---------------------------------------------------------------------------
def diagnose(
    client: MistClient,
    org_id: str,
    site: dict[str, Any],
    mac: str,
    duration: str,
) -> dict[str, Any]:
    site_id = site["id"]
    colon = format_mac(mac)
    jobs = {
        "stats": (f"/sites/{site_id}/stats/clients/{mac}", None),
        "search": (
            f"/sites/{site_id}/clients/search",
            {"mac": mac, "duration": duration, "limit": 20},
        ),
        "events": (
            f"/sites/{site_id}/clients/{mac}/events",
            {"duration": duration, "limit": EVENT_LIMIT},
        ),
        "sessions": (
            f"/sites/{site_id}/clients/sessions/search",
            {"mac": mac, "duration": duration, "limit": 50},
        ),
        "marvis": (
            f"/orgs/{org_id}/troubleshoot",
            {"mac": colon, "site_id": site_id},
        ),
    }
    out: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(client.get, path, params): key for key, (path, params) in jobs.items()}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                out[key] = fut.result()
            except MistError as exc:
                msg = str(exc)
                if key in {"stats", "search", "events"} and ("401" in msg or "403" in msg or "rate limit" in msg or "timed out" in msg):
                    raise
                out[key] = None
                if key != "marvis":
                    print(f"{Fore.YELLOW}[{key}] {exc}{RESET}")

    stats = None
    stats_rows = results_of(out.get("stats"))
    if stats_rows:
        stats = pick_stats(stats_rows[0])
    search_rows = [pick_stats(r) for r in results_of(out.get("search"))]
    if not stats and search_rows:
        stats = search_rows[0]
    events = [pick_event(r) for r in results_of(out.get("events"))]
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    sessions = [pick_session(r) for r in results_of(out.get("sessions"))]
    return {
        "demo": False,
        "host": client.host,
        "site_name": site.get("name") or site_id,
        "mac": mac,
        "duration": duration,
        "stats": stats,
        "events": events,
        "sessions": sessions,
        "marvis": out.get("marvis"),
        "verdict": build_verdict(stats, events, sessions),
    }


def render(result: dict[str, Any]) -> None:
    stats = result["stats"]
    events = result["events"]
    sessions = result["sessions"]
    verdict = result["verdict"]
    mac = format_mac(result["mac"])

    print()
    print(rule("="))
    title = "JUNIPER MIST  CLIENT DISCONNECT CONSOLE"
    print(f"{Fore.CYAN}{Style.BRIGHT}  {title}{RESET}")
    demo = "  [DEMO]" if result.get("demo") else ""
    print(f"  {result['host']}  |  {result['site_name']}  |  {mac}  |  {result['duration']}{demo}")
    print(rule("="))

    label = verdict["label"]
    score = verdict["score"]
    if label == "Critical":
        badge = paint("crit", f"  HEALTH {score:>3}   {label.upper()}  ", blink=True)
    elif label == "Degraded":
        badge = paint("warn", f"  HEALTH {score:>3}   {label.upper()}  ")
    else:
        badge = paint("good", f"  HEALTH {score:>3}   {label.upper()}  ")
    print()
    print(badge)
    print(f"  Primary cause : {Fore.WHITE}{Style.BRIGHT}{verdict['primaryCause']}{RESET}")
    for note in verdict["notes"]:
        flag = "crit" if re.search(r"critical|failure|timeout|weak", note, re.I) else "warn"
        print(f"    - {paint(flag, note)}")

    heading("LIVE / RECENT STATS")
    if not stats:
        print(f"  {Fore.YELLOW}No live stats for this MAC on the selected site.{RESET}")
    else:
        last = stats.get("last_seen")
        online = last is not None and (time.time() - last) < 300
        status = paint("good", "ONLINE") if online else paint("warn", "OFFLINE / STALE")
        kv("Status", status)
        kv("Hostname", stats.get("hostname") or "—")
        kv("Vendor / OS", f"{stats.get('manufacture') or '—'}  /  {stats.get('os') or '—'}")
        kv("SSID / VLAN", f"{stats.get('ssid') or '—'}  /  {stats.get('vlan') if stats.get('vlan') is not None else '—'}")
        kv("IP", stats.get("ip") or "—")
        kv("Username", stats.get("username") or "—")
        kv("Key mgmt", stats.get("key_mgmt") or "—")
        kv("AP", format_mac(str(stats.get("ap"))) if stats.get("ap") else "—")
        kv("Band / ch / proto", f"{stats.get('band') or '—'} / {stats.get('channel') or '—'} / {stats.get('proto') or '—'}")

        rssi = stats.get("rssi")
        snr = stats.get("snr")
        rb, sb = rssi_band(rssi), snr_band(snr)
        rssi_txt = "—" if rssi is None else f"{rssi:.0f} dBm"
        snr_txt = "—" if snr is None else f"{snr:.0f} dB"
        if rb == "crit":
            rssi_txt += "  << CRITICAL  (target >= -65)"
        elif rb == "warn":
            rssi_txt += "  << WARN"
        if sb == "crit":
            snr_txt += "  << CRITICAL  (target >= 25)"
        elif sb == "warn":
            snr_txt += "  << WARN"
        kv("RSSI", paint(rb, rssi_txt, blink=(rb == "crit")))
        kv("SNR", paint(sb, snr_txt, blink=(sb == "crit")))
        kv("TX / RX rate", f"{stats.get('tx_rate') or '—'}  /  {stats.get('rx_rate') or '—'}")
        kv("Traffic", f"{fmt_bytes(stats.get('tx_bytes'))} tx  /  {fmt_bytes(stats.get('rx_bytes'))} rx")
        kv("Uptime", fmt_duration(stats.get("uptime")))
        kv("Last seen", pretty_ts(stats.get("last_seen")))

    heading("EVENTS (newest first)")
    if not events:
        print("  (none in this window)")
    for ev in events[:40]:
        mark = paint("crit", "FAIL", blink=True) if ev["negative"] else paint("good", " OK ")
        print(f"  {mark}  {pretty_ts(ev['timestamp'])}  {ev['type']}")
        if ev["text"]:
            print(f"        {ev['text']}")
        extra_bits = []
        if ev.get("ap"):
            extra_bits.append(f"AP {format_mac(ev['ap']) if len(re.sub(r'[^0-9a-fA-F]', '', ev['ap'])) == 12 else ev['ap']}")
        if ev.get("ssid"):
            extra_bits.append(ev["ssid"])
        reason = describe_reason(ev.get("reason"))
        if reason:
            extra_bits.append(reason)
        if extra_bits:
            print(f"        {Fore.WHITE}{' · '.join(extra_bits)}{RESET}")

    if sessions:
        heading("SESSIONS")
        for s in sessions[:12]:
            dur = s.get("duration")
            short = dur is not None and 0 < dur < 60
            flag = paint("crit", "  SHORT", blink=True) if short else ""
            ap = format_mac(s["ap"]) if s.get("ap") and len(re.sub(r"[^0-9a-fA-F]", "", s["ap"])) == 12 else (s.get("ap") or "—")
            print(f"  AP {ap}  {s.get('ssid') or '—'}  {s.get('band') or ''}  {fmt_duration(dur)}{flag}")

    heading("MARVIS")
    marvis = result.get("marvis")
    if marvis:
        text = marvis if isinstance(marvis, str) else json.dumps(marvis, indent=2, default=str)
        print(text[:3000])
    else:
        print("  Not available (no subscription, empty result, or API error).")
    print()
    print(rule("-"))
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Juniper Mist client disconnect troubleshooter")
    p.add_argument("--host", default=DEFAULT_HOST, help=f"Mist API host (default {DEFAULT_HOST})")
    p.add_argument("--demo", action="store_true", help="Run the sample investigation (no token)")
    p.add_argument("--duration", default="1d", choices=("1h", "6h", "1d", "1w"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print(f"{Fore.CYAN}{Style.BRIGHT}Juniper Mist — Client Disconnect Troubleshooter{RESET}")
    print(f"Windows CLI dashboard   default host: {DEFAULT_HOST}")
    print()

    if args.demo:
        render(build_demo())
        return

    host = args.host.strip() or DEFAULT_HOST
    if host not in ALLOWED_HOSTS:
        entered = input(f"API host [{DEFAULT_HOST}]: ").strip() or DEFAULT_HOST
        host = entered
    if host not in ALLOWED_HOSTS:
        print("Host must be one of:")
        for h in ALLOWED_HOSTS:
            print(f"  {h}")
        sys.exit(1)
    print(f"API host: {host}")

    token = os.environ.get("MIST_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("Mist API token (hidden): ").strip()
    if not token:
        print("No token provided. Use --demo to see sample output.")
        sys.exit(1)

    client = MistClient(token, host)
    print("Validating token via GET /api/v1/self ...")
    self_info = client.get("/self")
    if not isinstance(self_info, dict):
        raise MistError("Empty /self response.")
    who = self_info.get("email") or self_info.get("name") or "API token"
    print(f"Authenticated as: {Fore.GREEN}{who}{RESET}")

    org_items = pick_orgs(self_info)
    if len(org_items) == 1:
        org_name, org_id = org_items[0]
        print(f"Organization: {org_name}")
    else:
        org_id = menu(org_items, "Select organization")
        org_name = next(n for n, i in org_items if i == org_id)
        print(f"Organization: {org_name}")

    sites = results_of(client.get(f"/orgs/{org_id}/sites"))
    if not sites:
        for p in self_info.get("privileges") or []:
            if isinstance(p, dict) and p.get("scope") == "site" and str(p.get("org_id")) == str(org_id):
                sites.append({"id": p.get("site_id"), "name": p.get("name") or p.get("site_id")})
    if not sites:
        raise MistError("No sites visible for this org/token.")
    sites.sort(key=lambda s: str(s.get("name") or "").lower())
    site = menu([(f"{s.get('name')}  ({s.get('id')})", s) for s in sites], "Select site")

    duration = args.duration
    while True:
        raw = input("Client MAC (or 'demo' / 'q'): ").strip()
        if raw.lower() in {"q", "quit", "exit"}:
            return
        if raw.lower() == "demo":
            render(build_demo())
        else:
            try:
                mac = normalize_mac(raw)
            except ValueError as exc:
                print(f"{Fore.YELLOW}{exc}{RESET}")
                continue
            print("Fetching stats, events, sessions, Marvis ...")
            render(diagnose(client, org_id, site, mac, duration))

        again = input("Investigate another MAC on this site? [y/N]: ").strip().lower()
        if again not in {"y", "yes"}:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except MistError as exc:
        print(f"{Fore.RED}{Style.BRIGHT}{exc}{RESET}")
        sys.exit(1)
