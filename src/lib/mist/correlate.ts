import { describeReason } from "./reason-codes.ts";
import { rssiBand, snrBand } from "./thresholds.ts";
import type { ClientEvent, ClientSession, ClientStats, Correlation } from "./types.ts";

const WINDOW_DHCP_S = 120;
const WINDOW_HANDSHAKE_S = 45;
const WINDOW_CLUSTER_S = 300;
const PINGPONG_MIN = 4;

function sortedAsc(events: ClientEvent[]): ClientEvent[] {
  return [...events].sort((a, b) => a.timestamp - b.timestamp);
}

function bandGroup(band: string | null | undefined): "24" | "5" | "6" | "unk" {
  const b = String(band ?? "").toLowerCase();
  if (b === "2" || b === "2.4" || b === "24" || b.includes("2.4")) return "24";
  if (b === "5" || b.includes("5")) return "5";
  if (b === "6" || b.includes("6")) return "6";
  return "unk";
}

function uniqueAps(items: { ap: string }[]): string[] {
  const set = new Set(items.map((x) => x.ap).filter(Boolean));
  return [...set];
}

export function buildCorrelations(
  stats: ClientStats | null,
  events: ClientEvent[],
  sessions: ClientSession[],
): Correlation[] {
  const out: Correlation[] = [];
  const chrono = sortedAsc(events);
  const rssi = stats?.rssi ?? null;
  const snr = stats?.snr ?? null;
  const rb = rssiBand(rssi);
  const sb = snrBand(snr);

  const deauth = events.filter((e) => /DEAUTH|DISASSOC/i.test(e.type));
  const dhcpFail = events.filter((e) => /DHCP/i.test(e.type) && e.negative);
  const dnsFail = events.filter((e) => /DNS/i.test(e.type) && e.negative);
  const assoc = events.filter((e) => /ASSOCIATION|ROAMED|AUTHORIZATION/i.test(e.type) && !e.negative);
  const roam = events.filter((e) => /ROAM/i.test(e.type));
  const handshake = deauth.filter(
    (e) => String(e.reason) === "15" || /4-way|handshake/i.test(`${e.type} ${e.text}`),
  );
  const idle = deauth.filter(
    (e) => String(e.reason) === "4" || /inactiv/i.test(`${e.type} ${e.text}`),
  );
  const leftBss = deauth.filter((e) => ["3", "8"].includes(String(e.reason)));

  if (rb === "crit" && sb === "crit") {
    out.push({
      id: "rf-coverage",
      title: "Coverage hole (weak RSSI and SNR together)",
      evidence: `Live RSSI ${rssi} dBm and SNR ${snr} dB. Mist treats RSSI < −75 dBm as a bad-roam / coverage signature; SNR < 15 dB confirms the client is at the edge or obstructed.`,
      confidence: "high",
      severity: "crit",
    });
  } else if (rb !== "crit" && rb !== "unknown" && sb === "crit") {
    out.push({
      id: "rf-noise",
      title: "Interference / noise (SNR collapsed while RSSI is still usable)",
      evidence: `RSSI ${rssi} dBm is not critical, but SNR ${snr} dB is. That pattern is noise, CCI, or a dirty channel — not a simple distance problem.`,
      confidence: "high",
      severity: "crit",
    });
  }

  for (const d of dhcpFail) {
    const prior = chrono.filter(
      (e) =>
        e.timestamp < d.timestamp &&
        d.timestamp - e.timestamp <= WINDOW_DHCP_S &&
        /ASSOCIATION|ROAMED|AUTHORIZATION|DEAUTH|DISASSOC/i.test(e.type),
    );
    if (prior.length) {
      const last = prior[prior.length - 1];
      out.push({
        id: `dhcp-after-join-${d.timestamp}`,
        title: "DHCP failed after join / roam — L3, not RF",
        evidence: `${last.type} at the prior AP, then ${d.type} ${Math.round(d.timestamp - last.timestamp)}s later. Association succeeded; DORA did not. Check VLAN, helper, and gateway on AP ${d.ap || last.ap || "—"}.`,
        confidence: "high",
        severity: "crit",
      });
      break;
    }
  }

  for (const h of handshake) {
    const prior = chrono.filter(
      (e) =>
        e.timestamp <= h.timestamp &&
        h.timestamp - e.timestamp <= WINDOW_HANDSHAKE_S &&
        /ASSOCIATION|AUTH/i.test(e.type),
    );
    if (prior.length || handshake.length) {
      out.push({
        id: `handshake-${h.timestamp}`,
        title: "4-way handshake timeout (PSK / 802.1X)",
        evidence: `${describeReason(h.reason ?? 15) ?? "reason 15"} on AP ${h.ap || "—"}. Classic mismatch of PSK, expired 802.1X, or a client that associated then failed key exchange.`,
        confidence: "high",
        severity: "crit",
      });
      break;
    }
  }

  if (idle.length && (rb === "crit" || rb === "warn")) {
    out.push({
      id: "sticky-idle",
      title: "Sticky client then inactivity deauth",
      evidence: `${idle.length} inactivity (reason 4) deauth(s) while RF is ${rssi} dBm. Client held a far AP until the AP aged it out — typical sticky-client / coverage-hole sequence in Mist roaming docs.`,
      confidence: "high",
      severity: "crit",
    });
  } else if (idle.length) {
    out.push({
      id: "idle-timeout",
      title: "Idle timeout deauth (reason 4)",
      evidence: `${idle.length} inactivity disconnect(s). Device slept, power-saved, or stopped transmitting; not necessarily an RF outage.`,
      confidence: "medium",
      severity: "warn",
    });
  }

  const apSeq = chrono.filter((e) => e.ap).map((e) => e.ap);
  let flips = 0;
  for (let i = 1; i < apSeq.length; i++) {
    if (apSeq[i] !== apSeq[i - 1]) flips++;
  }
  const aps = uniqueAps(chrono);
  if (flips >= PINGPONG_MIN && aps.length === 2) {
    out.push({
      id: "ping-pong",
      title: "AP ping-pong between two radios",
      evidence: `${flips} AP transitions oscillating across ${aps.join(" ↔ ")}. Overlapping cells, sticky 2.4/5, or a coverage saddle — not a single bad AP.`,
      confidence: "high",
      severity: "warn",
    });
  } else if (roam.length >= 4 || aps.length >= 3) {
    out.push({
      id: "excessive-roam",
      title: "Excessive roaming / AP hopping",
      evidence: `${roam.length} roam event(s) across ${aps.length} AP(s). Mist flags this as sticky-client or coverage-hole behavior when RSSI on the serving AP is poor.`,
      confidence: "medium",
      severity: "warn",
    });
  }

  for (let i = 1; i < chrono.length; i++) {
    const prev = chrono[i - 1];
    const cur = chrono[i];
    const from = bandGroup(prev.band);
    const to = bandGroup(cur.band);
    if (
      (from === "5" || from === "6") &&
      to === "24" &&
      /ROAM|ASSOCIATION/i.test(cur.type)
    ) {
      out.push({
        id: "band-drop",
        title: "Warning roam: dropped from 5/6 GHz to 2.4 GHz",
        evidence: `Band ${prev.band} → ${cur.band} during ${cur.type}. Mist marks inter-band jumps as warning roams; expect lower rates and more airtime contention.`,
        confidence: "high",
        severity: "warn",
      });
      break;
    }
  }

  const retries = stats?.txRetries ?? null;
  if (retries != null && retries >= 80 && (rb === "good" || rb === "warn")) {
    out.push({
      id: "retries-rf-ok",
      title: "High TX retries with usable RSSI (interference / multipath)",
      evidence: `${retries} TX retries while RSSI is ${rssi} dBm. Signal is present but frames are failing — CCI, non-Wi-Fi interference, or a hidden node, not a coverage hole.`,
      confidence: "medium",
      severity: "warn",
    });
  } else if (retries != null && retries >= 80 && rb === "crit") {
    out.push({
      id: "retries-edge",
      title: "High TX retries at the cell edge",
      evidence: `${retries} TX retries with RSSI ${rssi} dBm. Client is both weak and retrying — add coverage or reduce sticky behavior toward a nearer AP.`,
      confidence: "high",
      severity: "crit",
    });
  }

  const rate = stats?.txRate ?? null;
  if (rate != null && rate > 0 && rate < 24 && rb === "good") {
    out.push({
      id: "rate-mismatch",
      title: "PHY rate too low for the measured RSSI",
      evidence: `TX rate ${rate} Mbps with RSSI ${rssi} dBm. Capability, band, or retry backoff is capping throughput even though the RF looks fine.`,
      confidence: "medium",
      severity: "warn",
    });
  }

  const short = sessions.filter((s) => s.duration != null && s.duration > 0 && s.duration < 60);
  if (short.length >= 2) {
    const shortAps = uniqueAps(short);
    out.push({
      id: "short-sessions",
      title: "Unstable association (sessions under 60s)",
      evidence: `${short.length} session(s) lasted under a minute${shortAps.length === 1 ? ` — concentrated on AP ${shortAps[0]}` : ` across ${shortAps.length} AP(s)`}. Pair with the deauth reason on that radio.`,
      confidence: shortAps.length === 1 ? "high" : "medium",
      severity: "warn",
    });
  }

  const times = deauth.map((e) => e.timestamp).sort((a, b) => a - b);
  let cluster = 1;
  let maxCluster = 1;
  for (let i = 1; i < times.length; i++) {
    if (times[i] - times[i - 1] <= WINDOW_CLUSTER_S) {
      cluster += 1;
      maxCluster = Math.max(maxCluster, cluster);
    } else {
      cluster = 1;
    }
  }
  if (maxCluster >= 3) {
    out.push({
      id: "deauth-cluster",
      title: "Burst of disconnects (not an isolated drop)",
      evidence: `${maxCluster} deauth/disassoc events within ${WINDOW_CLUSTER_S / 60} minutes. Burst pattern points to a repeating cause (PSK, DHCP, or a flapping radio) rather than a one-off roam.`,
      confidence: "high",
      severity: "crit",
    });
  }

  if (dnsFail.length && dhcpFail.length === 0) {
    out.push({
      id: "dns-only",
      title: "DNS failed after a successful L2/L3 join",
      evidence: `${dnsFail.length} DNS failure(s) with no DHCP failure in the window. Wireless and DHCP are likely fine; inspect DNS reachability from that VLAN.`,
      confidence: "medium",
      severity: "warn",
    });
  }

  if (leftBss.length && !idle.length && rb === "good") {
    out.push({
      id: "client-left",
      title: "Client left the BSS (often user-initiated)",
      evidence: `${leftBss.length} leave-BSS reason(s) (3/8) while RF is healthy. Sleep, interface bounce, or the user walking away — not an infrastructure fault.`,
      confidence: "medium",
      severity: "info",
    });
  }

  const rank = { crit: 0, warn: 1, info: 2 };
  const conf = { high: 0, medium: 1, low: 2 };
  out.sort((a, b) => rank[a.severity] - rank[b.severity] || conf[a.confidence] - conf[b.confidence]);

  const seen = new Set<string>();
  return out.filter((c) => {
    const key = c.id;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
