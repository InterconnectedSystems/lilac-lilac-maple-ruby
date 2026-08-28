import { formatMac, hexMac } from "./mac.ts";
import { num, rssiBand, snrBand } from "./thresholds.ts";
import type {
  ApRadio,
  ClientEvent,
  ClientSession,
  ClientStats,
  CollabCall,
  Correlation,
  RadarAlert,
  RadarFact,
  RadioEvent,
} from "./types.ts";

export const RADIO_EVENTS_DURATION = "7d";
export const WINDOW_RADIO_DFS_S = 120;
export const WINDOW_RADIO_RRM_S = 300;
export const WINDOW_CALL_S = 30;
export const RRM_OTHER_KEEP = 200;
export const RRM_SLICE_1D_S = 3 * 3600;
export const RRM_SLICE_1W_S = 6 * 3600;
export const RRM_PAGES_SLICE_5 = 6;
export const RRM_PAGES_SLICE_OTHER = 1;
export const RRM_PAGES_SHORT_5 = 8;
export const RRM_PAGES_SHORT_OTHER = 2;
export const RRM_PAGES_ADAPT_5 = 24;
export const RRM_PAGES_LIVE_5 = 3;
export const RRM_PAGES_LIVE_OTHER = 1;
export const RRM_SCAN_PAGES_5 = RRM_PAGES_SLICE_5;
export const RRM_SCAN_PAGES_OTHER = RRM_PAGES_SLICE_OTHER;
export const RRM_PAGES_5 = RRM_PAGES_SLICE_5;
export const RRM_PAGES_OTHER = RRM_PAGES_SLICE_OTHER;
export const MAX_RADAR_CORRELATIONS = 80;

export const RRM_EVENT_LABELS: Record<string, string> = {
  "interference-ap-co-channel": "Interference AP co-channel",
  "interference-ap-non-wifi": "Interference AP non wifi",
  "neighbor-ap-down": "Neighbor AP down",
  "neighbor-ap-recovered": "Neighbor AP recovered",
  "radar-detected": "Radar detected",
  "rrm-radar": "Post radar",
  "scheduled-site_rrm": "Scheduled site RRM",
  "triggered-site_rrm": "Triggered site RRM",
};

const DISRUPTIVE_RADIO = new Set([
  "radar-detected",
  "rrm-radar",
  "interference-ap-co-channel",
  "interference-ap-non-wifi",
  "triggered-site_rrm",
]);

export function rrmEventLabel(event: string): string {
  const ev = (event || "").trim();
  if (RRM_EVENT_LABELS[ev]) return RRM_EVENT_LABELS[ev];
  return ev.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Radio event";
}

export function pickRrmEvent(raw: Record<string, unknown>): RadioEvent {
  const event = String(raw.event ?? raw.type ?? "");
  const preChannel = num(raw.pre_channel ?? raw.preChannel);
  const channel = num(raw.channel);
  let channelChanged = false;
  if (preChannel != null && channel != null && preChannel !== 0 && channel !== 0) {
    channelChanged = Math.trunc(preChannel) !== Math.trunc(channel);
  }
  return {
    timestamp: epochS(raw.timestamp) ?? 0,
    ap: hexMac(raw.ap ?? raw.ap_mac ?? raw.apMac ?? raw.mac ?? raw.device_mac ?? raw.deviceMac),
    apName: String(raw.ap_name ?? raw.apName ?? ""),
    band: String(raw.band ?? ""),
    channel,
    preChannel,
    bandwidth: num(raw.bandwidth),
    preBandwidth: num(raw.pre_bandwidth ?? raw.preBandwidth),
    power: num(raw.power),
    prePower: num(raw.pre_power ?? raw.prePower),
    event,
    label: rrmEventLabel(event),
    usage: String(raw.usage ?? ""),
    preUsage: String(raw.pre_usage ?? raw.preUsage ?? ""),
    channelChanged,
  };
}

export function qualityPoor(q: unknown): boolean {
  const n = num(q);
  if (n == null) return false;
  if (n > 5) return n < 50;
  return n <= 2 && n >= 0;
}

export function collabAppLabel(app: unknown): string {
  const a = String(app ?? "").trim().toLowerCase();
  if (!a) return "Unknown app";
  if (a.includes("team")) return "Microsoft Teams";
  if (a.includes("zoom")) return "Zoom";
  if (a.includes("webex")) return "Webex";
  if (a.includes("skype")) return "Skype";
  return String(app);
}

export function isTeamsApp(app: unknown): boolean {
  const a = String(app ?? "").trim().toLowerCase();
  return a.includes("team") || a.includes("skype");
}

export function pickCall(raw: Record<string, unknown>): CollabCall {
  const app = String(raw.app ?? "unknown");
  const start = num(raw.start_time ?? raw.start);
  const end = num(raw.end_time ?? raw.end);
  const duration = start != null && end != null && end > start ? end - start : null;
  const audioQuality = num(raw.audio_quality);
  const videoQuality = num(raw.video_quality);
  const screenShareQuality = num(raw.screen_share_quality);
  const rating = num(raw.rating);
  return {
    app,
    appLabel: collabAppLabel(app),
    mac: hexMac(raw.mac),
    meetingId: String(raw.meeting_id ?? raw.meetingId ?? ""),
    start,
    end,
    duration,
    audioQuality,
    videoQuality,
    screenShareQuality,
    rating,
    poor:
      qualityPoor(audioQuality) ||
      qualityPoor(videoQuality) ||
      qualityPoor(rating) ||
      qualityPoor(screenShareQuality),
    teams: isTeamsApp(app),
  };
}

export function sameApMac(a: unknown, b: unknown): boolean {
  const ha = hexMac(a);
  const hb = hexMac(b);
  return Boolean(ha && hb && ha === hb);
}

export function isRadarEvent(ev: Pick<RadioEvent, "event">): boolean {
  const e = String(ev.event || "").toLowerCase();
  return e === "radar-detected" || e === "rrm-radar" || e.includes("radar");
}

export function epochS(v: unknown): number | null {
  const n = num(v);
  if (n == null) return null;
  return Math.abs(n) >= 1e11 ? n / 1000 : n;
}

export function durationSeconds(duration: string): number {
  switch (String(duration || "").trim().toLowerCase()) {
    case "1h":
      return 3600;
    case "6h":
      return 6 * 3600;
    case "1d":
      return 86400;
    case "1w":
    case "7d":
      return 7 * 86400;
    default:
      return 86400;
  }
}

export function rrmTimeSlices(duration: string, now = Math.floor(Date.now() / 1000)): [number, number][] {
  const total = durationSeconds(duration);
  if (total <= 6 * 3600) return [[now - total, now]];
  const sliceS = total <= 86400 ? RRM_SLICE_1D_S : RRM_SLICE_1W_S;
  const out: [number, number][] = [];
  let end = now;
  let left = total;
  while (left > 0) {
    const length = Math.min(sliceS, left);
    const start = end - length;
    out.push([start, end]);
    end = start;
    left -= length;
  }
  return out;
}

export function rrmPagesForBand(band: string, duration: string): number {
  const short = durationSeconds(duration) <= 6 * 3600;
  if (String(band) === "5") return short ? RRM_PAGES_SHORT_5 : RRM_PAGES_SLICE_5;
  return short ? RRM_PAGES_SHORT_OTHER : RRM_PAGES_SLICE_OTHER;
}

export function deviceRadioMacs(dev: Record<string, unknown> | null | undefined): Set<string> {
  const out = new Set<string>();
  if (!dev) return out;
  for (const k of ["mac", "ap", "ap_mac", "bssid", "radio_mac"]) {
    const h = hexMac(dev[k]);
    if (h.length === 12) out.add(h);
  }
  const rs = dev.radio_stat;
  if (rs && typeof rs === "object") {
    for (const v of Object.values(rs as Record<string, unknown>)) {
      if (!v || typeof v !== "object") continue;
      const rec = v as Record<string, unknown>;
      for (const k of ["mac", "bssid", "ap_mac", "radio_mac"]) {
        const h = hexMac(rec[k]);
        if (h.length === 12) out.add(h);
      }
    }
  }
  return out;
}

export function expandClientAps(
  sessions: ClientSession[] | null | undefined,
  events: ClientEvent[] | null | undefined,
  stats: ClientStats | null | undefined,
  inventory: Record<string, unknown>[] | null | undefined,
): Set<string> {
  const seeds = new Set<string>();
  for (const s of sessions ?? []) {
    for (const k of [s.ap, s.bssid]) {
      const h = hexMac(k);
      if (h.length === 12) seeds.add(h);
    }
  }
  for (const e of events ?? []) {
    const h = hexMac(e.ap);
    if (h.length === 12) seeds.add(h);
  }
  const live = hexMac(stats?.ap);
  if (live.length === 12) seeds.add(live);
  const families = (inventory ?? []).map(deviceRadioMacs);
  const out = new Set(seeds);
  let changed = true;
  while (changed) {
    changed = false;
    for (const g of families) {
      let hit = false;
      for (const m of g) if (out.has(m)) hit = true;
      if (!hit) continue;
      for (const m of g) {
        if (!out.has(m)) {
          out.add(m);
          changed = true;
        }
      }
    }
  }
  return out;
}

/** AP-keyed RRM index. Correlation looks up radars by the session AP, never scans the site firehose. */
export class RadioEventStore {
  clientAps: Set<string>;
  canon = new Map<string, string>();
  members = new Map<string, Set<string>>();
  byAp = new Map<string, RadioEvent[]>();
  radarsByAp = new Map<string, RadioEvent[]>();
  radars: RadioEvent[] = [];
  kept: RadioEvent[] = [];
  others: RadioEvent[] = [];
  scanned = 0;
  dropped = 0;

  constructor(clientAps?: Iterable<string> | null, families?: Iterable<Set<string>> | null) {
    for (const g of families ?? []) {
      const cleaned = new Set([...g].map(hexMac).filter((h) => h.length === 12));
      if (!cleaned.size) continue;
      const root = [...cleaned].sort()[0]!;
      const mem = this.members.get(root) ?? new Set<string>();
      for (const m of cleaned) {
        mem.add(m);
        this.canon.set(m, root);
      }
      this.members.set(root, mem);
    }
    const seeds = [...(clientAps ?? [])].map(hexMac).filter((h) => h.length === 12);
    const expanded = new Set<string>();
    for (const s of seeds) {
      const root = this.canon.get(s) ?? s;
      expanded.add(s);
      expanded.add(root);
      for (const m of this.members.get(root) ?? []) expanded.add(m);
    }
    this.clientAps = expanded;
  }

  key(mac: unknown): string {
    const h = hexMac(mac);
    return this.canon.get(h) ?? h;
  }

  related(a: unknown, b: unknown): boolean {
    const ha = hexMac(a);
    const hb = hexMac(b);
    if (!ha || !hb) return false;
    if (ha === hb) return true;
    const ka = this.key(ha);
    const kb = this.key(hb);
    return Boolean(ka && ka === kb);
  }

  add(ev: RadioEvent | null | undefined): string {
    if (!ev) return "skip";
    this.scanned += 1;
    const ap = hexMac(ev.ap);
    const radar = isRadarEvent(ev);
    let onClient = true;
    if (ap && this.clientAps.size) {
      onClient = this.clientAps.has(ap);
      if (!onClient) {
        for (const c of this.clientAps) {
          if (this.related(ap, c)) {
            onClient = true;
            break;
          }
        }
      }
    } else if (this.clientAps.size) {
      onClient = false;
    }

    if (radar) {
      this.radars.push(ev);
      if (ap) {
        const list = this.radarsByAp.get(ap) ?? [];
        list.push(ev);
        this.radarsByAp.set(ap, list);
        const ck = this.key(ap);
        if (ck && ck !== ap) {
          const cl = this.radarsByAp.get(ck) ?? [];
          cl.push(ev);
          this.radarsByAp.set(ck, cl);
        }
      }
    }

    let keep = false;
    let keepAsOther = false;
    if (radar) keep = onClient;
    else if (onClient) keep = true;
    else if (this.others.length < RRM_OTHER_KEEP) {
      keep = true;
      keepAsOther = true;
    }
    if (!keep) {
      this.dropped += 1;
      return radar ? "radar" : "drop";
    }
    this.kept.push(ev);
    if (ap) {
      const list = this.byAp.get(ap) ?? [];
      list.push(ev);
      this.byAp.set(ap, list);
      const ck = this.key(ap);
      if (ck && ck !== ap) {
        const cl = this.byAp.get(ck) ?? [];
        cl.push(ev);
        this.byAp.set(ck, cl);
      }
    }
    if (keepAsOther) this.others.push(ev);
    if (radar) return "radar-client";
    return onClient ? "client" : "other";
  }

  addMany(events: RadioEvent[] | null | undefined): void {
    for (const ev of events ?? []) this.add(ev);
  }

  radarsOnAp(ap: unknown): RadioEvent[] {
    const h = hexMac(ap);
    const keys = new Set<string>([h, this.key(h), ...(this.members.get(this.key(h)) ?? [])]);
    const seen = new Set<string>();
    const out: RadioEvent[] = [];
    for (const k of keys) {
      for (const re of this.radarsByAp.get(k) ?? []) {
        const sig = `${re.ap}|${re.timestamp}|${re.event}|${re.channel}`;
        if (seen.has(sig)) continue;
        seen.add(sig);
        out.push(re);
      }
    }
    return out;
  }

  hitsForSession(sess: ClientSession): RadioEvent[] {
    const out: RadioEvent[] = [];
    const seen = new Set<string>();
    for (const mac of [sess.ap, sess.bssid]) {
      for (const re of this.radarsOnAp(mac)) {
        const sig = `${re.ap}|${re.timestamp}|${re.event}`;
        if (seen.has(sig)) continue;
        if (sessionCovers(sess, epochS(re.timestamp) ?? 0)) {
          seen.add(sig);
          out.push(re);
        }
      }
    }
    out.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
    return out;
  }

  hitsForSessions(sessions: ClientSession[] | null | undefined): { sess: ClientSession; re: RadioEvent }[] {
    const pairs: { sess: ClientSession; re: RadioEvent }[] = [];
    for (const s of sessions ?? []) {
      for (const re of this.hitsForSession(s)) pairs.push({ sess: s, re });
    }
    return pairs;
  }

  clientRadarEvents(sessions: ClientSession[] | null | undefined): RadioEvent[] {
    const seen = new Set<string>();
    const rows: RadioEvent[] = [];
    for (const { re } of this.hitsForSessions(sessions)) {
      const key = `${re.ap}|${re.timestamp}|${re.event}|${re.channel}`;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push(re);
    }
    rows.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
    return rows;
  }

  exportEvents(): RadioEvent[] {
    const seen = new Set<string>();
    const out: RadioEvent[] = [];
    for (const ev of this.kept) {
      const key = `${ev.ap}|${ev.timestamp}|${ev.event}|${ev.channel}|${ev.band}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(ev);
    }
    out.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
    return out;
  }
}

export function buildRadioStore(
  events: RadioEvent[] | null | undefined,
  clientAps?: Iterable<string> | null,
  families?: Iterable<Set<string>> | null,
): RadioEventStore {
  const store = new RadioEventStore(clientAps, families);
  store.addMany(events);
  return store;
}

export function powerChanged(ev: Pick<RadioEvent, "prePower" | "power">): boolean {
  if (ev.prePower == null || ev.power == null) return false;
  return Math.abs(ev.power - ev.prePower) >= 3;
}

export function bandHzLabel(b: unknown): string {
  const s = String(b ?? "").trim().toLowerCase();
  if (s === "24" || s === "2.4" || s === "2") return "2.4 GHz";
  if (s === "6") return "6 GHz";
  if (!s) return "—";
  return "5 GHz";
}

export function arrowVals(pre: unknown, cur: unknown, unit = ""): string {
  if (pre == null || pre === "" || pre === 0 || String(pre) === String(cur)) {
    return cur == null || cur === "" ? "—" : `${cur}${unit}`;
  }
  if (cur == null || cur === "") return `${pre}${unit}`;
  return `${pre}${unit} → ${cur}${unit}`;
}

export function apNameFor(
  mac: unknown,
  radioEvents: RadioEvent[] | null | undefined,
  apRadio: ApRadio | null | undefined,
): string {
  const h = hexMac(mac);
  if (!h) return "—";
  if (apRadio && sameApMac(apRadio.apMac, h) && apRadio.apName) return apRadio.apName;
  for (const re of radioEvents ?? []) {
    if (sameApMac(re.ap, h) && re.apName) return re.apName;
  }
  return formatMac(h);
}

export function radarFact(
  re: RadioEvent,
  clientAp: string,
  clientName: string,
  opts?: { call?: CollabCall | null; drop?: ClientEvent | null },
): RadarFact {
  const call = opts?.call;
  const drop = opts?.drop;
  return {
    call: call?.appLabel ?? null,
    meetingId: call?.meetingId || null,
    callStart: call?.start ?? null,
    callEnd: call?.end ?? null,
    callDuration: call?.duration ?? null,
    audioQuality: call?.audioQuality ?? null,
    videoQuality: call?.videoQuality ?? null,
    clientAp: hexMac(clientAp) || null,
    clientApName: clientName || null,
    radarEvent: re.label || re.event,
    radarType: re.event,
    radarTime: re.timestamp,
    radarAp: hexMac(re.ap) || null,
    radarApName: re.apName || null,
    radarChannel: arrowVals(re.preChannel, re.channel),
    radarWidth: arrowVals(re.preBandwidth, re.bandwidth, " MHz"),
    radarPower: arrowVals(re.prePower, re.power, " dBm"),
    radarBand: `${bandHzLabel(re.preUsage || re.band)} → ${bandHzLabel(re.usage || re.band)}`,
    dropType: drop?.type ?? null,
    dropTime: drop?.timestamp ?? null,
  };
}

export function sessionCovers(sess: ClientSession, t: number): boolean {
  const ts = epochS(t) ?? 0;
  const start = epochS(sess.connect);
  if (start == null || start === 0) return false;
  const endRaw = epochS(sess.disconnect);
  const end = endRaw == null || endRaw === 0 || endRaw < start ? ts + 1 : endRaw;
  return start - 2 <= ts && ts <= end + 2;
}

export function sessionOnApAt(
  sessions: ClientSession[] | null | undefined,
  t: number,
  ap: unknown,
): ClientSession | null {
  const hits = (sessions ?? []).filter(
    (s) => sessionCovers(s, t) && (sameApMac(s.ap, ap) || sameApMac(s.bssid, ap)),
  );
  if (!hits.length) return null;
  hits.sort((a, b) => (b.connect ?? 0) - (a.connect ?? 0));
  return hits[0];
}

export function clientApAt(
  sessions: ClientSession[] | null | undefined,
  events: ClientEvent[] | null | undefined,
  stats: ClientStats | null | undefined,
  t: number,
): string {
  const covering: { start: number; ap: string }[] = [];
  for (const s of sessions ?? []) {
    if (s.connect == null || !s.ap) continue;
    if (sessionCovers(s, t)) covering.push({ start: s.connect, ap: hexMac(s.ap) });
  }
  if (covering.length) {
    covering.sort((a, b) => b.start - a.start);
    return covering[0].ap;
  }
  const prior = (events ?? []).filter((e) => (e.timestamp || 0) <= t + 2 && e.ap);
  if (prior.length) {
    prior.sort((a, b) => a.timestamp - b.timestamp);
    return hexMac(prior[prior.length - 1].ap);
  }
  const live = hexMac(stats?.ap);
  if (live && Math.abs(Date.now() / 1000 - t) <= 300) return live;
  return "";
}

export function radarHitsThisClient(
  re: RadioEvent,
  sessions: ClientSession[] | null | undefined,
  events: ClientEvent[] | null | undefined,
  stats: ClientStats | null | undefined,
): { same: boolean; onAp: string } {
  const onAp = clientApAt(sessions, events, stats, re.timestamp || 0);
  if (!onAp || !re.ap) return { same: false, onAp };
  return { same: sameApMac(onAp, re.ap), onAp };
}

export function annotateRadioEvents(
  radioEvents: RadioEvent[],
  events: ClientEvent[],
  sessions: ClientSession[],
  stats: ClientStats | null,
): RadioEvent[] {
  for (const re of radioEvents) {
    const onAp = clientApAt(sessions, events, stats, re.timestamp || 0);
    re.onClientAp = sameApMac(onAp, re.ap);
    re.highlight = Boolean(isRadarEvent(re) && re.onClientAp);
  }
  return radioEvents;
}

export function attachApNames<T extends { ap?: string; apName?: string }>(
  rows: T[],
  inventory: Record<string, unknown>[] | null | undefined,
): T[] {
  const names = new Map<string, string>();
  for (const d of inventory ?? []) {
    const m = hexMac(d.mac);
    if (m) names.set(m, String(d.name ?? ""));
  }
  for (const re of rows) {
    if (!re.apName) re.apName = names.get(hexMac(re.ap)) || "";
  }
  return rows;
}

export function radarSessionAlerts(
  radioEvents: RadioEvent[],
  sessions: ClientSession[] | null | undefined,
  calls: CollabCall[] | null | undefined,
  apRadio: ApRadio | null | undefined,
  store?: RadioEventStore | null,
): RadarAlert[] {
  const st =
    store ??
    buildRadioStore(
      radioEvents,
      (sessions ?? []).flatMap((s) => [s.ap, s.bssid ?? ""]),
    );
  const raw: RadarAlert[] = [];
  for (const { sess, re } of st.hitsForSessions(sessions)) {
    const ts = epochS(re.timestamp) ?? 0;
    const apMac = hexMac(sess.ap);
    const apName = sess.apName || apNameFor(apMac, radioEvents, apRadio);
    const overlappingCall = (calls ?? []).find((c) => callOpenAt(c, ts)) ?? null;
    const fact = radarFact(re, apMac, apName, { call: overlappingCall });
    let meet = "";
    if (overlappingCall) {
      meet = ` ${overlappingCall.appLabel}${overlappingCall.meetingId ? ` meeting ${overlappingCall.meetingId}` : ""} was in progress.`;
    }
    const radio: RadioEvent = { ...re, highlight: true, onClientAp: true, apName: re.apName || apName };
    const summary =
      `This client's session on ${apName} (${formatMac(apMac)}) was active when ` +
      `${re.label || "Post radar"} hit that same AP (channel ${fact.radarChannel}).${meet} ` +
      "DFS vacates 5 GHz and deauthenticates every associated station.";
    raw.push({
      id: `session-radar-${re.timestamp}-${apMac}`,
      severity: "crit",
      title: `Session was on this AP during ${re.label || "Post radar"}`,
      summary,
      sessionAp: apMac,
      sessionApName: apName,
      sessionConnect: sess.connect,
      sessionDisconnect: sess.disconnect,
      sessionDuration: sess.duration,
      radarEvent: re.label || re.event,
      radarTime: re.timestamp,
      radarAp: hexMac(re.ap),
      radarApName: re.apName || apName,
      radarChannel: fact.radarChannel,
      radarWidth: fact.radarWidth,
      radarPower: fact.radarPower,
      radarBand: fact.radarBand,
      call: overlappingCall?.appLabel ?? null,
      meetingId: overlappingCall?.meetingId ?? null,
      callStart: overlappingCall?.start ?? null,
      callEnd: overlappingCall?.end ?? null,
      detail: fact,
      session: {
        ap: apMac,
        apName,
        ssid: sess.ssid,
        band: sess.band,
        connect: sess.connect,
        disconnect: sess.disconnect,
        duration: sess.duration,
        hitByRadar: true,
      },
      radio,
      radios: [radio],
    });
  }
  const grouped = new Map<string, RadarAlert>();
  const order: string[] = [];
  for (const a of raw) {
    const key = `${a.sessionAp}|${a.sessionConnect}`;
    const host = grouped.get(key);
    if (!host) {
      grouped.set(key, a);
      order.push(key);
      continue;
    }
    host.radios = [...(host.radios ?? [host.radio]), ...(a.radios ?? [a.radio])];
    if (!host.call && a.call) {
      host.call = a.call;
      host.meetingId = a.meetingId;
      host.callStart = a.callStart;
      host.callEnd = a.callEnd;
    }
  }
  const out: RadarAlert[] = [];
  for (const key of order) {
    const a = grouped.get(key)!;
    const radios = [...(a.radios ?? (a.radio ? [a.radio] : []))].sort(
      (x, y) => (y.timestamp || 0) - (x.timestamp || 0),
    );
    a.radios = radios;
    a.radio = radios[0] ?? a.radio;
    if (radios.length > 1) {
      a.title = `Session was on this AP during ${radios.length} radar events`;
      a.summary =
        `This client's session on ${a.sessionApName} (${formatMac(a.sessionAp)}) ` +
        `was associated while ${radios.length} DFS / Post radar events hit that same AP. ` +
        "Each event is listed under this banner. DFS vacates 5 GHz and deauthenticates every associated station.";
      a.id = `session-radar-${a.sessionConnect}-${a.sessionAp}`;
    }
    out.push(a);
  }
  for (const s of sessions ?? []) {
    s.radarHits = out
      .filter((a) => sameApMac(s.ap, a.sessionAp) && s.connect === a.sessionConnect)
      .flatMap((a) => (a.radios ?? [a.radio]).map((r) => r.timestamp ?? 0));
    s.hitByRadar = Boolean(s.radarHits.length);
  }
  return out;
}

function clientDrops(events: ClientEvent[]): ClientEvent[] {
  return events.filter((e) => /DEAUTH|DISASSOC|DISCONNECT|ROAM/i.test(e.type));
}

export function radioEventCorrelations(
  radioEvents: RadioEvent[],
  events: ClientEvent[],
  sessions: ClientSession[] | null | undefined,
  stats: ClientStats | null | undefined,
  apRadio: ApRadio | null | undefined,
  store?: RadioEventStore | null,
): Correlation[] {
  if (!radioEvents.length && !store) return [];
  const st =
    store ??
    buildRadioStore(
      radioEvents,
      expandClientAps(sessions, events, stats, null),
    );
  const drops = clientDrops(events ?? []);
  const out: Correlation[] = [];
  let radarKept = 0;
  const seenRadar = new Set<string>();
  for (const { sess, re } of st.hitsForSessions(sessions)) {
    if (!isRadarEvent(re)) continue;
    const sig = `${re.ap}|${re.timestamp}|${re.event}`;
    if (seenRadar.has(sig)) continue;
    seenRadar.add(sig);
    if (radarKept >= MAX_RADAR_CORRELATIONS) continue;
    const ts = epochS(re.timestamp) ?? 0;
    const onAp = hexMac(sess.ap);
    const window = WINDOW_RADIO_DFS_S;
    const hits: { dt: number; d: ClientEvent }[] = [];
    for (const d of drops) {
      const dt = (epochS(d.timestamp) ?? 0) - ts;
      if (dt < -15 || dt > window) continue;
      if (st.related(d.ap, re.ap) || sameApMac(d.ap, re.ap)) hits.push({ dt, d });
    }
    hits.sort((a, b) => Math.abs(a.dt) - Math.abs(b.dt));
    const drop = hits[0]?.d;
    const dt = hits[0]?.dt;
    const apn = formatMac(re.ap || "");
    const uid = `${re.timestamp}-${hexMac(re.ap) || "ap"}`;
    const clientName = apNameFor(onAp, radioEvents, apRadio);
    const radarName = re.apName || apn;
    const fact = radarFact(re, onAp, clientName, { drop });
    const evidence = drop
      ? `${re.label} at radar AP ${radarName} (${apn}), channel ${fact.radarChannel}. Client was on ${clientName} (${formatMac(onAp)}) — same AP. ${drop.type} ${Math.round(dt)}s later. DFS vacates 5 GHz immediately.`
      : `${re.label} at radar AP ${radarName} (${apn}), channel ${fact.radarChannel}. Client was connected to ${clientName} (${formatMac(onAp)}) — same AP as the radar event. No matching deauth in the client log, but DFS still forces a channel change.`;
    out.push({
      id: `radio-radar-${uid}`,
      title: `${re.label} on the AP this client was connected to`,
      evidence,
      confidence: "high",
      severity: "crit",
      highlight: true,
      detail: fact,
    });
    radarKept += 1;
  }

  const clientAps = st.clientAps.size ? st.clientAps : expandClientAps(sessions, events, stats, null);
  for (const re of radioEvents) {
    const ts = epochS(re.timestamp) ?? 0;
    const reAp = hexMac(re.ap);
    if (isRadarEvent(re)) continue;
    if (reAp && clientAps.size) {
      let related = clientAps.has(reAp);
      if (!related) {
        for (const c of clientAps) {
          if (st.related(reAp, c)) {
            related = true;
            break;
          }
        }
      }
      if (!related) continue;
    }
    const { same: connected, onAp } = radarHitsThisClient(re, sessions, events, stats);
    const window = WINDOW_RADIO_RRM_S;
    const hits: { dt: number; d: ClientEvent }[] = [];
    for (const d of drops) {
      const dt = (epochS(d.timestamp) ?? 0) - ts;
      if (dt < -15 || dt > window) continue;
      if (connected || sameApMac(d.ap, re.ap)) hits.push({ dt, d });
    }
    hits.sort((a, b) => Math.abs(a.dt) - Math.abs(b.dt));
    const drop = hits[0]?.d;
    const dt = hits[0]?.dt;
    const chBit = re.channelChanged ? ` Channel ${re.preChannel ?? 0} → ${re.channel ?? 0}.` : "";
    const pwrBit = powerChanged(re) ? ` Power ${re.prePower} → ${re.power} dBm.` : "";
    const apn = formatMac(re.ap || "");
    const uid = `${re.timestamp}-${reAp || "ap"}`;

    if (!DISRUPTIVE_RADIO.has(re.event) && !re.channelChanged && !powerChanged(re)) continue;
    if (!connected && !drop) continue;

    if (re.event === "neighbor-ap-down" && connected) {
      out.push({
        id: `radio-neighbor-${re.timestamp}`,
        title: "Neighbor AP went down while this client was on it",
        evidence: `Neighbor-AP-down on ${apn} while the client session was there.${drop ? ` ${drop.type} ${Math.round(dt)}s later.` : ""} Remaining APs absorb the cell — expect a burst of roams and weaker RSSI.`,
        confidence: "high",
        severity: "crit",
      });
      continue;
    }
    if (re.channelChanged && connected) {
      out.push({
        id: `radio-channel-${re.timestamp}`,
        title: `AP channel change while client was associated (${re.label})`,
        evidence: `${re.label} on AP ${apn}.${chBit}${drop ? ` ${drop.type} ${Math.round(dt)}s later.` : " Client was on this radio at the change."} A mid-session channel change is a forced roam.`,
        confidence: "high",
        severity: "warn",
      });
      continue;
    }
    if (powerChanged(re) && connected && !re.channelChanged) {
      out.push({
        id: `radio-power-${re.timestamp}`,
        title: "RRM power change on the AP this client was on",
        evidence: `${re.label} on AP ${apn}.${pwrBit} A sudden drop in TX power shrinks the cell and looks like a coverage hole to a mid-cell client.`,
        confidence: "medium",
        severity: "warn",
      });
      continue;
    }
    if (drop) {
      out.push({
        id: `radio-${re.event}-${re.timestamp}`,
        title: `Client drop after ${(re.label || "radio event").toLowerCase()}`,
        evidence: `${re.label} on AP ${apn} then ${drop.type} ${Math.round(dt)}s later.${chBit}${pwrBit}`,
        confidence: "medium",
        severity: "warn",
      });
    }
  }
  return out;
}

export function callOpenAt(call: CollabCall, t: number): boolean {
  const start = call.start || 0;
  const end = call.end || start;
  return start - WINDOW_CALL_S <= t && t <= end + WINDOW_CALL_S;
}

export function callCorrelations(
  calls: CollabCall[],
  events: ClientEvent[],
  sessions: ClientSession[] | null | undefined,
  stats: ClientStats | null | undefined,
  radioEvents: RadioEvent[] | null | undefined,
  apRadio: ApRadio | null | undefined,
  store?: RadioEventStore | null,
): Correlation[] {
  if (!calls.length) return [];
  const drops = (events ?? []).filter((e) => /DEAUTH|DISASSOC|DISCONNECT/i.test(e.type));
  const roams = (events ?? []).filter((e) => /ROAM/i.test(e.type));
  const dhcpFail = (events ?? []).filter((e) => /DHCP/i.test(e.type) && e.negative);
  const handshake = drops.filter(
    (e) => String(e.reason) === "15" || /4-way|handshake/i.test(`${e.type} ${e.text}`),
  );
  const rssi = stats?.rssi ?? null;
  const snr = stats?.snr ?? null;
  const retries = stats?.txRetries ?? null;
  const rb = rssiBand(rssi);
  const sb = snrBand(snr);
  const out: Correlation[] = [];
  const radars = (radioEvents ?? []).filter(isRadarEvent);

  for (const c of calls) {
    const label = c.appLabel || "Call";
    const overlapping = drops.filter((d) => callOpenAt(c, d.timestamp || 0));
    const roamHits = roams.filter((d) => callOpenAt(c, d.timestamp || 0));
    const dhcpHits = dhcpFail.filter((d) => callOpenAt(c, d.timestamp || 0));
    const hsHits = handshake.filter((d) => callOpenAt(c, d.timestamp || 0));
    const radarHits = store
      ? (() => {
          const seen = new Set<string>();
          const rows: RadioEvent[] = [];
          for (const { re } of store.hitsForSessions(sessions)) {
            if (!callOpenAt(c, epochS(re.timestamp) ?? 0)) continue;
            const sig = `${re.ap}|${re.timestamp}|${re.event}`;
            if (seen.has(sig)) continue;
            seen.add(sig);
            rows.push(re);
          }
          rows.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
          return rows;
        })()
      : radars
          .filter((re) => callOpenAt(c, epochS(re.timestamp) ?? 0) && radarHitsThisClient(re, sessions, events, stats).same)
          .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
    const start = c.start || 0;

    if (radarHits.length) {
      for (const re of radarHits) {
        const onAp = clientApAt(sessions, events, stats, epochS(re.timestamp) ?? 0);
        const clientName = apNameFor(onAp, radioEvents, apRadio);
        const radarName = re.apName || formatMac(re.ap || "");
        const fact = radarFact(re, onAp, clientName, { call: c, drop: overlapping[0] });
        const meet = c.meetingId ? ` meeting ${c.meetingId}` : "";
        out.push({
          id: `call-radar-${c.start}-${re.timestamp}-${hexMac(re.ap)}`,
          title: `${label} in progress during ${re.label}`,
          evidence: `${label}${meet} ${Math.round(c.duration || 0)}s (audio ${c.audioQuality ?? "—"} / video ${c.videoQuality ?? "—"}). Client AP at radar time: ${clientName} (${onAp ? formatMac(onAp) : "—"}). ${re.label} on ${radarName} (${formatMac(re.ap || "")}), channel ${fact.radarChannel}, ${fact.radarWidth}, ${fact.radarPower}.`,
          confidence: "high",
          severity: "crit",
          highlight: true,
          detail: fact,
        });
      }
      continue;
    }
    if (overlapping.length) {
      const d = overlapping[0];
      const endedAtDrop = Boolean(c.end && Math.abs(c.end - (d.timestamp || 0)) <= 20);
      let extra = "";
      if (hsHits.length) extra = " 4-way handshake timeout during the call — media path died with the keys.";
      else if (dhcpHits.length) extra = " DHCP failed during the call — L3, not Teams.";
      out.push({
        id: `call-drop-${c.start}`,
        title: endedAtDrop
          ? `${label} dropped with the wireless disconnect`
          : `${label} overlapped a wireless disconnect`,
        evidence: `${label} ${Math.round(c.duration || 0)}s, audio ${c.audioQuality ?? "—"}, video ${c.videoQuality ?? "—"}. ${d.type} at ${d.timestamp}.${extra} The call failure is the wireless event, not a Teams outage.`,
        confidence: "high",
        severity: c.poor || endedAtDrop ? "crit" : "warn",
      });
      continue;
    }
    if (roamHits.length && (c.poor || roamHits.length >= 2)) {
      out.push({
        id: `call-roam-${c.start}`,
        title: `${label} during AP roam / ping-pong`,
        evidence: `${roamHits.length} roam(s) while ${label} was up. Each roam is a brief media blackout; two or more in a meeting is choppy audio even if RSSI recovers.`,
        confidence: c.poor ? "high" : "medium",
        severity: "warn",
      });
      continue;
    }
    if (c.poor && retries != null && retries >= 80) {
      out.push({
        id: `call-retries-${c.start}`,
        title: `Poor ${label} quality with high TX retries`,
        evidence: `${label} audio ${c.audioQuality} / video ${c.videoQuality} with ${retries} TX retries. Airtime contention or interference, not a Teams cloud issue.`,
        confidence: "high",
        severity: rb === "crit" || rb === "warn" ? "crit" : "warn",
      });
      continue;
    }
    if (c.poor) {
      const audioOnly = qualityPoor(c.audioQuality) && !qualityPoor(c.videoQuality);
      if (rb === "crit" || rb === "warn" || sb === "crit" || sb === "warn") {
        out.push({
          id: `call-rf-${c.start}`,
          title: `Poor ${label} quality with weak RF`,
          evidence: `${label} audio ${c.audioQuality} / video ${c.videoQuality} while RSSI ${rssi} dBm and SNR ${snr} dB. Real-time media is the first thing coverage holes break.`,
          confidence: "high",
          severity: "crit",
        });
      } else if (audioOnly && rb === "good") {
        out.push({
          id: `call-qos-${c.start}`,
          title: `Poor ${label} audio while Wi-Fi RF and video look fine`,
          evidence: `Audio ${c.audioQuality} but video ${c.videoQuality} at RSSI ${rssi} dBm. Classic missing DSCP/WMM or WAN jitter — not an AP coverage hole.`,
          confidence: "medium",
          severity: "warn",
        });
      } else {
        out.push({
          id: `call-qos-${c.start}`,
          title: `Poor ${label} quality while Wi-Fi RF looks fine`,
          evidence: `${label} audio ${c.audioQuality} / video ${c.videoQuality} with RSSI ${rssi} dBm. Not a coverage hole — check WAN/NAT, DSCP/WMM, or the Teams client path.`,
          confidence: "medium",
          severity: "warn",
        });
      }
      continue;
    }
    if (c.duration != null && c.duration > 0 && c.duration < 20) {
      const assoc = (events ?? []).filter(
        (e) => /ASSOCIAT/i.test(e.type) && Math.abs((e.timestamp || 0) - start) <= 45,
      );
      if (assoc.length) {
        out.push({
          id: `call-join-${c.start}`,
          title: `${label} died right after Wi-Fi join`,
          evidence: `${label} lasted ${Math.round(c.duration)}s starting next to ${assoc[0].type}. Client associated, then the meeting never got a stable media path.`,
          confidence: "medium",
          severity: "warn",
        });
      }
    }
  }
  const poorTeams = calls.filter((c) => c.teams && c.poor);
  if (poorTeams.length >= 2 && !out.some((x) => String(x.id).startsWith("call-"))) {
    out.push({
      id: "call-repeat-poor",
      title: "Repeated poor Microsoft Teams calls in 7 days",
      evidence: `${poorTeams.length} poor Teams sessions for this MAC over 7 days. Pattern, not a one-off meeting.`,
      confidence: "medium",
      severity: "warn",
    });
  }
  return out;
}
