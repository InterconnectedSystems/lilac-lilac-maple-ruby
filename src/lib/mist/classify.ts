import { buildCorrelations } from "./correlate.ts";
import { rfOccupancyCorrelations } from "./occupancy.ts";
import { callCorrelations, epochS, radioEventCorrelations, type RadioEventStore } from "./radio.ts";
import { describeReason } from "./reason-codes.ts";
import { num, rssiBand, snrBand } from "./thresholds.ts";
import type {
  ApRadio,
  ClientEvent,
  ClientSession,
  ClientStats,
  CollabCall,
  HealthVerdict,
  RadioEvent,
} from "./types.ts";

const NEGATIVE = [
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
  "BLOCKED",
];

export function isNegativeEvent(type: string, text: string): boolean {
  const hay = `${type} ${text}`.toUpperCase();
  if (hay.includes("DEAUTH") || hay.includes("DISASSOC")) return true;
  const success =
    hay.includes("SUCCESS") ||
    hay.includes("_OK") ||
    hay.includes(" OK") ||
    hay.includes("JOINED") ||
    hay.includes("ASSIGNED") ||
    hay.includes("ASSOCIATION") ||
    hay.includes("REASSOCIATION") ||
    hay.includes("AUTHORIZATION");
  if (
    success &&
    !["FAIL", "DENIED", "TIMEOUT", "TIMED_OUT", "TERMINATED", "BAD_IP", "BAD IP"].some((k) =>
      hay.includes(k),
    )
  ) {
    return false;
  }
  return NEGATIVE.some((k) => hay.includes(k));
}

function asBool(v: unknown): boolean | null {
  if (typeof v === "boolean") return v;
  if (v === 1 || v === "1" || v === "true") return true;
  if (v === 0 || v === "0" || v === "false") return false;
  return null;
}

export function pickStats(raw: Record<string, unknown>): ClientStats {
  return {
    mac: String(raw.mac ?? ""),
    hostname: (raw.hostname as string) || (raw.device as string) || null,
    manufacture:
      (raw.manufacture as string) || (raw.client_manufacture as string) || null,
    os: (raw.os as string) || null,
    model: (raw.model as string) || null,
    ssid: (raw.ssid as string) || null,
    vlan: (raw.vlan_id as string | number) ?? (raw.vlan as string | number) ?? null,
    ip: (raw.ip as string) || (raw.ip6 as string) || null,
    ap: (raw.ap as string) || (raw.ap_mac as string) || null,
    band: raw.band != null ? String(raw.band) : null,
    channel: (raw.channel as string | number) ?? null,
    proto: (raw.proto as string) || (raw.protocol as string) || null,
    rssi: num(raw.rssi ?? raw.rssi_dbm),
    snr: num(raw.snr ?? raw.snr_db),
    txRate: num(raw.tx_rate),
    rxRate: num(raw.rx_rate),
    uptime: num(raw.uptime),
    lastSeen: num(raw.last_seen ?? raw.timestamp),
    txBytes: num(raw.tx_bytes),
    rxBytes: num(raw.rx_bytes),
    username: (raw.username as string) || null,
    keyMgmt: (raw.key_mgmt as string) || null,
    txRetries: num(raw.tx_retries ?? raw.num_tx_retries ?? raw.tx_retry),
    rxRetries: num(raw.rx_retries ?? raw.num_rx_retries ?? raw.rx_retry),
    dualBand: asBool(raw.dual_band),
  };
}

export function pickEvent(raw: Record<string, unknown>): ClientEvent {
  const type = String(raw.type ?? raw.type_code ?? "unknown");
  const text = String(raw.text ?? "");
  return {
    timestamp: num(raw.timestamp) ?? 0,
    type,
    text,
    ap: String(raw.ap ?? ""),
    ssid: String(raw.ssid ?? ""),
    band: String(raw.band ?? ""),
    channel: (raw.channel as string | number) ?? null,
    reason: (raw.reason_code as string | number) ?? (raw.reason as string | number) ?? null,
    negative: isNegativeEvent(type, text),
  };
}

export function pickSession(raw: Record<string, unknown>): ClientSession {
  const ap = String(raw.ap ?? raw.ap_mac ?? "");
  const bssid = String(raw.bssid ?? "");
  return {
    ap: ap || bssid,
    bssid,
    apName: String(raw.ap_name ?? raw.apName ?? ""),
    ssid: String(raw.ssid ?? ""),
    band: String(raw.band ?? ""),
    connect: epochS(raw.connect),
    disconnect: epochS(raw.disconnect),
    duration: num(raw.duration),
  };
}

export function buildVerdict(
  stats: ClientStats | null,
  events: ClientEvent[],
  sessions: ClientSession[],
  apRadio: ApRadio | null = null,
  radioEvents: RadioEvent[] = [],
  calls: CollabCall[] = [],
  radioStore: RadioEventStore | null = null,
): HealthVerdict {
  const notes: string[] = [];
  const correlations = [
    ...buildCorrelations(stats, events, sessions),
    ...rfOccupancyCorrelations(apRadio, stats),
    ...radioEventCorrelations(radioEvents, events, sessions, stats, apRadio, radioStore),
    ...callCorrelations(calls, events, sessions, stats, radioEvents, apRadio, radioStore),
  ];

  const rssi = stats?.rssi ?? null;
  const snr = stats?.snr ?? null;
  const rb = rssiBand(rssi);
  const sb = snrBand(snr);

  if (rb === "crit") {
    notes.push(`RSSI ${rssi} dBm is critically weak — coverage or obstruction.`);
  } else if (rb === "warn") {
    notes.push(`RSSI ${rssi} dBm is marginal (target ≥ −65 dBm).`);
  }

  if (sb === "crit") {
    notes.push(`SNR ${snr} dB is critically low — noise or interference likely.`);
  } else if (sb === "warn") {
    notes.push(`SNR ${snr} dB is only fair (target ≥ 25 dB).`);
  }

  const deauth = events.filter((e) => /DEAUTH|DISASSOC/i.test(e.type));
  const dhcp = events.filter((e) => /DHCP/i.test(e.type) && e.negative);
  const auth = events.filter(
    (e) =>
      e.negative &&
      /AUTH|ASSOC/i.test(e.type) &&
      !/DEAUTH|DISASSOC/i.test(e.type),
  );
  const roam = events.filter((e) => /ROAM/i.test(e.type));

  if (deauth.length) {
    const reasons = [
      ...new Set(
        deauth
          .map((e) => describeReason(e.reason ?? undefined))
          .filter(Boolean),
      ),
    ];
    notes.push(
      `${deauth.length} deauth/disassoc event(s)${reasons.length ? `: ${reasons.join("; ")}` : ""}.`,
    );
  }
  if (dhcp.length) {
    notes.push(`${dhcp.length} DHCP failure(s) after association — L3 / gateway.`);
  }
  if (auth.length) {
    notes.push(`${auth.length} authentication/association failure(s).`);
  }
  if (roam.length >= 4) {
    notes.push(`${roam.length} roam events in the window — sticky client or coverage holes.`);
  }

  const short = sessions.filter((s) => s.duration != null && s.duration > 0 && s.duration < 60);
  if (short.length >= 2) {
    notes.push(`${short.length} sessions lasted under 60s — unstable association.`);
  }

  const retries = stats?.txRetries ?? null;
  if (retries != null && retries >= 80) {
    notes.push(`${retries} TX retries — airtime contention or a dirty channel.`);
  }

  const serving = apRadio?.channels.find((c) => c.serving);
  const nw = serving?.nonWifi ?? apRadio?.radio?.utilNonWifi ?? 0;
  if (nw >= 25) {
    const ch = serving?.channel ?? apRadio?.radio?.channel;
    notes.push(`Serving AP channel ${ch} has ${nw}% non-Wi-Fi occupancy.`);
  }

  const radioHits = correlations.filter((c) => c.id.startsWith("radio-") && c.severity === "crit");
  if (radioHits.length) {
    notes.push(`${radioHits.length} Radio Management event(s) on the AP this client was connected to.`);
  }
  const callHits = correlations.filter((c) => c.id.startsWith("call-") && (c.severity === "crit" || c.severity === "warn"));
  if (callHits.length) {
    notes.push(`${callHits.length} Teams/collaboration call issue(s) overlapping wireless events.`);
  }

  const rank = { crit: 0, warn: 1, info: 2 };
  const conf = { high: 0, medium: 1, low: 2 };
  correlations.sort(
    (a, b) =>
      (a.highlight ? 0 : 1) - (b.highlight ? 0 : 1) ||
      rank[a.severity] - rank[b.severity] ||
      conf[a.confidence] - conf[b.confidence],
  );
  const seen = new Set<string>();
  const uniq = correlations.filter((c) => {
    const key = c.id;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  correlations.length = 0;
  correlations.push(...uniq);

  for (const c of correlations.filter((x) => x.severity === "crit" && x.confidence === "high")) {
    if (!notes.some((n) => n.includes(c.title.slice(0, 18)))) {
      notes.push(c.title);
    }
  }

  let primaryCause = "No dominant failure signature — review the timeline.";
  const top = correlations[0];
  if (top && (top.severity === "crit" || top.severity === "warn")) {
    primaryCause = top.title;
  } else if (rb === "crit" || sb === "crit") {
    primaryCause = "RF: weak signal or high noise";
  } else if (auth.length) {
    primaryCause = "Authentication / association failure";
  } else if (dhcp.length) {
    primaryCause = "DHCP / IP services after join";
  } else if (deauth.length) {
    primaryCause = "Repeated disconnects — see reason codes";
  }

  if (!notes.length) notes.push("RF metrics in range and no clustered failure events.");

  return { primaryCause, notes, correlations };
}
