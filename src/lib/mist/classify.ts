import { buildCorrelations } from "./correlate.ts";
import { rfOccupancyCorrelations } from "./occupancy.ts";
import { describeReason } from "./reason-codes.ts";
import { num, rssiBand, snrBand } from "./thresholds.ts";
import type { ApRadio, ClientEvent, ClientSession, ClientStats, HealthVerdict } from "./types.ts";

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
  if (hay.includes("SUCCESS") || hay.includes("OK") || hay.includes("JOINED")) {
    if (!hay.includes("FAIL")) return false;
  }
  // Do not treat AUTH as a substring — ASSOCIATION / AUTHORIZATION contain "AUTH"
  // and would mark every successful join as a failure.
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
  return {
    ap: String(raw.ap ?? ""),
    ssid: String(raw.ssid ?? ""),
    band: String(raw.band ?? ""),
    connect: num(raw.connect),
    disconnect: num(raw.disconnect),
    duration: num(raw.duration),
  };
}

export function buildVerdict(
  stats: ClientStats | null,
  events: ClientEvent[],
  sessions: ClientSession[],
  apRadio: ApRadio | null = null,
): HealthVerdict {
  const notes: string[] = [];
  let score = 100;
  const correlations = [
    ...buildCorrelations(stats, events, sessions),
    ...rfOccupancyCorrelations(apRadio, stats),
  ];

  const rssi = stats?.rssi ?? null;
  const snr = stats?.snr ?? null;
  const rb = rssiBand(rssi);
  const sb = snrBand(snr);

  if (rb === "crit") {
    score -= 25;
    notes.push(`RSSI ${rssi} dBm is critically weak — coverage or obstruction.`);
  } else if (rb === "warn") {
    score -= 12;
    notes.push(`RSSI ${rssi} dBm is marginal (target ≥ −65 dBm).`);
  }

  if (sb === "crit") {
    score -= 20;
    notes.push(`SNR ${snr} dB is critically low — noise or interference likely.`);
  } else if (sb === "warn") {
    score -= 10;
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
    score -= Math.min(30, deauth.length * 6);
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
    score -= 15;
    notes.push(`${dhcp.length} DHCP failure(s) after association — L3 / gateway.`);
  }
  if (auth.length) {
    score -= 15;
    notes.push(`${auth.length} authentication/association failure(s).`);
  }
  if (roam.length >= 4) {
    score -= 8;
    notes.push(`${roam.length} roam events in the window — sticky client or coverage holes.`);
  }

  const short = sessions.filter((s) => s.duration != null && s.duration > 0 && s.duration < 60);
  if (short.length >= 2) {
    score -= 10;
    notes.push(`${short.length} sessions lasted under 60s — unstable association.`);
  }

  const retries = stats?.txRetries ?? null;
  if (retries != null && retries >= 80) {
    score -= 8;
    notes.push(`${retries} TX retries — airtime contention or a dirty channel.`);
  }

  const serving = apRadio?.channels.find((c) => c.serving);
  const nw = serving?.nonWifi ?? apRadio?.radio?.utilNonWifi ?? 0;
  if (nw >= 25) {
    score -= nw >= 40 ? 10 : 6;
    const ch = serving?.channel ?? apRadio?.radio?.channel;
    notes.push(`Serving AP channel ${ch} has ${nw}% non-Wi-Fi occupancy.`);
  }

  const rank = { crit: 0, warn: 1, info: 2 };
  const conf = { high: 0, medium: 1, low: 2 };
  correlations.sort(
    (a, b) => rank[a.severity] - rank[b.severity] || conf[a.confidence] - conf[b.confidence],
  );
  const seen = new Set<string>();
  const uniq = correlations.filter((c) => {
    const key = c.id.replace(/-\d+$/, "");
    if (seen.has(key)) return false;
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

  score = Math.max(0, Math.min(100, score));
  const label: HealthVerdict["label"] =
    score >= 80 ? "Healthy" : score >= 50 ? "Degraded" : "Critical";

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

  return { score, label, primaryCause, notes, correlations };
}
