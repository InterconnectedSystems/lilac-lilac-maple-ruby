import { formatMac, hexMac } from "./mac.ts";
import { num } from "./thresholds.ts";
import type { ApRadio, ClientStats, Correlation, OccupancyBar, RadioLive } from "./types.ts";

export const OCC_5_DEFAULT = [100, 104, 108, 112, 116, 132, 136, 140, 144, 149, 153, 157, 161, 165];
export const OCC_UNII1 = [36, 40, 44, 48];
export const OCC_UNII2 = [52, 56, 60, 64];
export const OCC_UNII2_EXT = [100, 104, 108, 112, 116, 132, 136, 140, 144];
export const OCC_UNII3 = [149, 153, 157, 161, 165];
export const OCC_24 = [1, 6, 11];

export type UniiFilter = "all" | "unii-1" | "unii-2" | "unii-2ext" | "unii-3";

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** radio_stat integers: 1 = 1%. Do not treat 1 as a 0–1 fraction. */
export function radioPct(v: unknown): number {
  const n = num(v);
  if (n == null) return 0;
  if (n > 1) return Math.max(0, Math.min(100, Math.round(n)));
  if (Number.isInteger(n)) return Math.max(0, Math.min(100, n));
  if (n >= 0 && n <= 1) return Math.round(n * 100);
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** RRM wifi / non_wifi / util_score: 0–1 floats, including 1.0 = 100%. */
export function occPct(v: unknown): number {
  const n = num(v);
  if (n == null) return 0;
  if (n > 1) return Math.max(0, Math.min(100, Math.round(n)));
  if (n >= 0 && n <= 1) return Math.round(n * 100);
  return 0;
}

export function stackPcts(site: number, external: number, nonWifi: number): [number, number, number] {
  let s = Math.max(0, site);
  let e = Math.max(0, external);
  let n = Math.max(0, nonWifi);
  const tot = s + e + n;
  if (tot > 100) {
    s = Math.round((s * 100) / tot);
    e = Math.round((e * 100) / tot);
    n = Math.max(0, 100 - s - e);
  }
  return [s, e, n];
}

function heardRssi(v: unknown): number | null {
  const n = num(v);
  if (n == null || n === 0) return null;
  return n;
}

export function rrmRowsFrom(raw: unknown): Record<string, unknown>[] {
  if (raw == null) return [];
  if (Array.isArray(raw)) {
    const out: Record<string, unknown>[] = [];
    for (const x of raw) {
      if (!x || typeof x !== "object" || Array.isArray(x)) continue;
      const rec = x as Record<string, unknown>;
      if (rec.channel != null || rec.chan != null || rec.ch != null) out.push(rec);
      else out.push(...rrmRowsFrom(rec));
    }
    return out;
  }
  const rec = asRecord(raw);
  if (!rec) return [];
  for (const key of ["results", "channels", "channel_usage", "considerations", "data", "items"]) {
    if (rec[key] != null) {
      const got = rrmRowsFrom(rec[key]);
      if (got.length) return got;
    }
  }
  const keys = Object.keys(rec);
  if (keys.length && keys.every((k) => num(k) != null)) {
    return keys.map((k) => {
      const v = asRecord(rec[k]) ?? {};
      return { ...v, channel: v.channel ?? Number(k) };
    });
  }
  return [];
}

function occField(row: Record<string, unknown>, ...names: string[]): number {
  const nested = asRecord(row.occupancy) ?? {};
  const usage = asRecord(row.channel_usage) ?? {};
  for (const n of names) {
    for (const src of [row, nested, usage]) {
      if (src[n] != null) {
        const p = occPct(src[n]);
        if (p) return p;
      }
    }
  }
  return 0;
}

export function rrmOccupancyStack(
  row: Record<string, unknown>,
  siteOnChannel = false,
): [number, number, number] {
  let nw = occField(row, "non_wifi", "nonWifi", "non_wifi_occupancy");
  if (nw === 0) nw = occField(row, "util_score_non_wifi", "util_non_wifi");
  let wifi = occField(row, "wifi", "wifi_occupancy", "util_wifi", "occupancy_wifi");
  if (wifi === 0) wifi = occField(row, "util_score_other", "util_other", "other", "util_rx_other_bss");
  const rssi = heardRssi(row.rssi);
  const otherRssi = heardRssi(row.other_rssi);
  const otherSsid = String(row.other_ssid ?? "").trim();
  if (wifi <= 0) return stackPcts(0, 0, nw);
  const siteHeard = rssi != null;
  const extHeard = otherRssi != null || Boolean(otherSsid);
  if (siteHeard && !extHeard) return stackPcts(wifi, 0, nw);
  if (extHeard && !siteHeard) return stackPcts(0, wifi, nw);
  if (siteHeard && extHeard && rssi != null && otherRssi != null) {
    const wr = 10 ** (rssi / 10);
    const wo = 10 ** (otherRssi / 10);
    const den = wr + wo || 1;
    const site = Math.round((wifi * wr) / den);
    const ext = Math.max(0, wifi - site);
    return stackPcts(site, ext, nw);
  }
  if (siteHeard || siteOnChannel) return stackPcts(wifi, 0, nw);
  return stackPcts(0, wifi, nw);
}

export function bandGroup(band: unknown): "24" | "5" | "6" | "unk" {
  const b = String(band ?? "").toLowerCase();
  if (b === "2" || b === "2.4" || b === "24" || b.includes("2.4")) return "24";
  if (b === "5" || b.includes("5")) return "5";
  if (b === "6" || b.includes("6")) return "6";
  return "unk";
}

export function radioFromDevice(
  dev: Record<string, unknown>,
  bandHint: string,
): [Record<string, unknown>, string] {
  const rs = asRecord(dev.radio_stat) ?? {};
  const wanted = bandGroup(bandHint);
  const keys: Record<string, string> = { "24": "band_24", "5": "band_5", "6": "band_6" };
  const order = [keys[wanted] ?? "band_5", "band_5", "band_6", "band_24"];
  const seen = new Set<string>();
  for (const key of order) {
    if (seen.has(key)) continue;
    seen.add(key);
    const rec = asRecord(rs[key]);
    if (rec && (rec.channel != null || rec.num_clients != null || rec.power != null)) {
      return [rec, key.replace("band_", "")];
    }
  }
  return [{}, wanted === "unk" ? "5" : wanted];
}

export function siteAirtime(radio: Record<string, unknown>): number {
  if (!radio || !Object.keys(radio).length) return 0;
  const tx = radioPct(radio.util_tx);
  const inn = radioPct(radio.util_rx_in_bss ?? radio.util_in_bss);
  const air = Math.min(100, tx + inn);
  if (air) return air;
  const allu = radioPct(radio.util_all);
  const nw = radioPct(radio.util_non_wifi);
  const oth = radioPct(radio.util_rx_other_bss) + radioPct(radio.util_unknown_wifi);
  const leftover = Math.max(0, allu - nw - oth);
  if (leftover) return leftover;
  if (radio.channel != null && radio.power != null) return 8;
  return 0;
}

export function siteAirtimeByChannel(
  inventory: Record<string, unknown>[],
  band: string,
): Record<number, number> {
  const sums: Record<number, number> = {};
  const want = bandGroup(band);
  for (const d of inventory) {
    const [radio, b] = radioFromDevice(d, band);
    if (want !== "unk" && bandGroup(b) !== want && bandGroup(b) !== "unk") continue;
    const ch = Math.trunc(num(radio.channel) ?? 0);
    if (!ch) continue;
    sums[ch] = Math.min(100, (sums[ch] ?? 0) + siteAirtime(radio));
  }
  return sums;
}

export function servingChannelRow(radio: Record<string, unknown>, channel: unknown): OccupancyBar {
  let site = radioPct(radio.util_rx_in_bss ?? radio.util_in_bss);
  let external = radioPct(radio.util_rx_other_bss ?? radio.util_other_bss) + radioPct(radio.util_unknown_wifi);
  let nonWifi = radioPct(radio.util_non_wifi);
  if (site + external + nonWifi === 0) {
    nonWifi = Math.max(0, radioPct(radio.util_all) - radioPct(radio.util_tx));
  }
  const [s, e, n] = stackPcts(site, external, nonWifi);
  return {
    channel: Math.trunc(num(channel) ?? 0),
    site: s,
    external: e,
    nonWifi: n,
    serving: true,
  };
}

export function padBandChannels(band: string, servingCh: number, have: Set<number>): number[] {
  const extra: number[] = [];
  if (OCC_5_DEFAULT.includes(servingCh) || band === "5") extra.push(...OCC_5_DEFAULT);
  if (OCC_UNII1.includes(servingCh)) extra.push(...OCC_UNII1);
  if (OCC_UNII2.includes(servingCh)) extra.push(...OCC_UNII2);
  if (band === "24" || OCC_24.includes(servingCh)) extra.push(...OCC_24);
  const out: number[] = [];
  const seen = new Set<number>();
  for (const ch of [...have, ...extra]) {
    if (ch && !seen.has(ch)) {
      seen.add(ch);
      out.push(ch);
    }
  }
  out.sort((a, b) => a - b);
  return out;
}

export function channelsFromRrm(
  rows: Record<string, unknown>[],
  servingCh: unknown,
  servingRadio: Record<string, unknown> | null,
  band = "5",
  siteChannels: Record<number, number> | null = null,
): OccupancyBar[] {
  const servingN = Math.trunc(num(servingCh) ?? 0);
  const siteAir = siteChannels ?? {};
  const byCh = new Map<number, OccupancyBar>();
  for (const row of rows) {
    const ch = Math.trunc(num(row.channel ?? row.chan ?? row.ch) ?? 0);
    if (!ch) continue;
    let [s, e, n] = rrmOccupancyStack(row, ch in siteAir);
    if (s === 0 && siteAir[ch]) [s, e, n] = stackPcts(siteAir[ch], e, n);
    byCh.set(ch, { channel: ch, site: s, external: e, nonWifi: n, serving: ch === servingN });
  }
  for (const [ch, air] of Object.entries(siteAir)) {
    const c = Number(ch);
    const existing = byCh.get(c);
    if (!existing) {
      byCh.set(c, { channel: c, site: air, external: 0, nonWifi: 0, serving: c === servingN });
    } else if (existing.site === 0 && air) {
      const [s, e, n] = stackPcts(air, existing.external, existing.nonWifi);
      byCh.set(c, { ...existing, site: s, external: e, nonWifi: n });
    }
  }
  for (const ch of padBandChannels(band, servingN, new Set(byCh.keys()))) {
    const existing = byCh.get(ch);
    if (!existing) byCh.set(ch, { channel: ch, site: 0, external: 0, nonWifi: 0, serving: ch === servingN });
    else existing.serving = ch === servingN;
  }
  const out = [...byCh.values()].sort((a, b) => a.channel - b.channel);
  if (servingN && !byCh.has(servingN) && servingRadio) {
    out.push(servingChannelRow(servingRadio, servingN));
    out.sort((a, b) => a.channel - b.channel);
  }
  return out;
}

export function liveRadio(radio: Record<string, unknown>): RadioLive {
  return {
    channel: num(radio.channel),
    bandwidth: (radio.bandwidth as number | string | null) ?? null,
    power: num(radio.power),
    numClients: num(radio.num_clients),
    utilAll: radioPct(radio.util_all),
    utilTx: radioPct(radio.util_tx),
    utilRxInBss: radioPct(radio.util_rx_in_bss),
    utilRxOtherBss: radioPct(radio.util_rx_other_bss),
    utilNonWifi: radioPct(radio.util_non_wifi),
    utilUnknownWifi: radioPct(radio.util_unknown_wifi),
    utilUndecodable: radioPct(radio.util_undecodable_wifi),
  };
}

export function filterOccupancy(channels: OccupancyBar[], filter: UniiFilter): OccupancyBar[] {
  if (filter === "all") return channels;
  const set =
    filter === "unii-1"
      ? OCC_UNII1
      : filter === "unii-2"
        ? OCC_UNII2
        : filter === "unii-2ext"
          ? OCC_UNII2_EXT
          : OCC_UNII3;
  return channels.filter((c) => set.includes(c.channel));
}

export function rfOccupancyCorrelations(
  apRadio: ApRadio | null | undefined,
  stats: ClientStats | null,
): Correlation[] {
  const out: Correlation[] = [];
  if (!apRadio || apRadio.unavailable) return out;
  const radio = apRadio.radio;
  const channels = apRadio.channels ?? [];
  const serving = channels.find((c) => c.serving);
  const ch = serving?.channel ?? radio?.channel;
  const nw = serving?.nonWifi ?? radio?.utilNonWifi ?? 0;
  const ext = serving?.external ?? (radio ? radio.utilRxOtherBss + radio.utilUnknownWifi : 0);
  const site = serving?.site ?? radio?.utilRxInBss ?? 0;
  const name = apRadio.apName || formatMac(apRadio.apMac || "");
  if (nw >= 25) {
    out.push({
      id: "ap-nonwifi",
      title: "Non-Wi-Fi interference on the serving AP channel",
      evidence: `AP ${name} sees ${nw}% non-Wi-Fi occupancy on channel ${ch} (Radio Management 20-min scan). Frames collide with energy that is not 802.11 — radar, video, BLE, or industrial interferers — which matches high TX retries while RSSI stays usable.`,
      confidence: nw >= 40 ? "high" : "medium",
      severity: nw >= 40 ? "crit" : "warn",
    });
  }
  if (ext >= 30 && nw < 40) {
    out.push({
      id: "ap-external-cci",
      title: "External AP occupancy (CCI / hidden node)",
      evidence: `AP ${name} channel ${ch} has ${ext}% occupancy from other BSS (external APs) and ${site}% from site APs. Foreign BSSIDs on this channel cause retries without a coverage hole.`,
      confidence: "medium",
      severity: "warn",
    });
  }
  const hot = channels.filter((c) => !c.serving && c.nonWifi >= 50);
  if (hot.length && ch != null) {
    const nearest = hot.reduce((a, b) =>
      Math.abs(b.channel - Number(ch)) < Math.abs(a.channel - Number(ch)) ? b : a,
    );
    if (Math.abs(nearest.channel - Number(ch)) <= 16) {
      out.push({
        id: "ap-adj-nonwifi",
        title: "Adjacent-channel non-Wi-Fi energy",
        evidence: `Channel ${nearest.channel} shows ${nearest.nonWifi}% non-Wi-Fi next to serving channel ${ch}. Bleed and AGC pumping on the client can look like a dirty serving channel.`,
        confidence: "medium",
        severity: "warn",
      });
    }
  }
  void stats;
  return out;
}
