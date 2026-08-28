import { buildVerdict, pickEvent, pickSession, pickStats } from "./classify";
import { mergeInventory, pickDominantAp } from "./ap-select";
import { isMistHost, type MistHost } from "./hosts";
import { formatMac, hexMac, mistDeviceId, normalizeMac } from "./mac";
import {
  channelsFromRrm,
  liveRadio,
  radioFromDevice,
  rrmRowsFrom,
  servingChannelRow,
  siteAirtimeByChannel,
} from "./occupancy";
import {
  annotateRadioEvents,
  attachApNames,
  buildRadioStore,
  deviceRadioMacs,
  durationSeconds,
  expandClientAps,
  pickCall,
  pickRrmEvent,
  radarSessionAlerts,
  rrmPagesForBand,
  rrmTimeSlices,
  RADIO_EVENTS_DURATION,
  RRM_PAGES_ADAPT_5,
  RRM_PAGES_LIVE_5,
  RRM_PAGES_LIVE_OTHER,
} from "./radio";
import type {
  ApRadio,
  ClientEvent,
  ClientSession,
  ClientStats,
  CollabCall,
  ConnectResult,
  DiagnoseResult,
  DurationKey,
  MistOrg,
  MistSite,
  RadioEvent,
} from "./types";

const TIMEOUT_MS = 25_000;

function stripTokenPrefix(token: string): string {
  return token.replace(/^token\s+/i, "").trim();
}

async function mistGet(
  host: MistHost,
  token: string,
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<unknown> {
  if (!isMistHost(host)) throw new Error("Host is not a known Mist API region.");
  const url = new URL(`https://${host}/api/v1${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    }
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: `Token ${stripTokenPrefix(token)}`,
        Accept: "application/json",
      },
      signal: ctrl.signal,
    });
    if (res.status === 204) return null;
    if (res.status === 401) {
      throw new Error("Token rejected (401). Check region and token.");
    }
    if (res.status === 403) {
      throw new Error("Token lacks permission for this org or site (403).");
    }
    if (res.status === 404) return null;
    if (res.status === 429) {
      throw new Error("Mist rate limit (429). Wait a minute and retry.");
    }
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`Mist API ${res.status}: ${body.slice(0, 180) || res.statusText}`);
    }
    const text = await res.text();
    if (!text) return null;
    return JSON.parse(text) as unknown;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error("Mist API timed out after 25s.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function asArray(v: unknown): Record<string, unknown>[] {
  if (Array.isArray(v)) return v.filter((x) => x && typeof x === "object") as Record<string, unknown>[];
  const rec = asRecord(v);
  if (rec && Array.isArray(rec.results)) {
    return rec.results.filter((x) => x && typeof x === "object") as Record<string, unknown>[];
  }
  return [];
}

export async function connectMist(input: {
  token: string;
  host: MistHost;
}): Promise<ConnectResult> {
  const self = asRecord(await mistGet(input.host, input.token, "/self"));
  if (!self) throw new Error("Empty /self response.");

  const orgs = new Map<string, string>();
  const privileges = Array.isArray(self.privileges) ? self.privileges : [];
  for (const p of privileges) {
    const rec = asRecord(p);
    if (!rec) continue;
    if (rec.scope === "org" && typeof rec.org_id === "string") {
      orgs.set(rec.org_id, String(rec.name ?? rec.org_id));
    }
  }
  if (typeof self.org_id === "string" && !orgs.has(self.org_id)) {
    orgs.set(self.org_id, String(self.name ?? self.org_id));
  }
  if (orgs.size === 0) throw new Error("No organization privileges on this token.");

  const email = String(self.email ?? self.name ?? "API token");
  return {
    email,
    orgs: [...orgs.entries()].map(([id, name]) => ({ id, name })),
  };
}

export async function listSites(input: {
  token: string;
  host: MistHost;
  orgId: string;
}): Promise<MistSite[]> {
  const data = await mistGet(input.host, input.token, `/orgs/${input.orgId}/sites`);
  const rows = asArray(data);
  const sites: MistSite[] = rows
    .map((r) => ({
      id: String(r.id ?? ""),
      name: String(r.name ?? r.id ?? "Unnamed"),
    }))
    .filter((s) => s.id);
  sites.sort((a, b) => a.name.localeCompare(b.name));
  if (!sites.length) {
    // Fall back to site-scoped privileges on /self
    const self = asRecord(await mistGet(input.host, input.token, "/self"));
    const privileges = Array.isArray(self?.privileges) ? self!.privileges : [];
    for (const p of privileges) {
      const rec = asRecord(p);
      if (rec?.scope === "site" && rec.org_id === input.orgId && typeof rec.site_id === "string") {
        sites.push({ id: rec.site_id, name: String(rec.name ?? rec.site_id) });
      }
    }
  }
  if (!sites.length) throw new Error("No sites visible for this org/token.");
  return sites;
}

export async function diagnoseClient(input: {
  token: string;
  host: MistHost;
  orgId: string;
  siteId: string;
  siteName: string;
  mac: string;
  duration: DurationKey;
  live?: boolean;
}): Promise<DiagnoseResult> {
  const mac = normalizeMac(input.mac);
  const colonMac = formatMac(mac);

  const statsPath = `/sites/${input.siteId}/stats/clients/${mac}`;
  const searchPath = `/sites/${input.siteId}/clients/search`;
  const eventsPath = `/sites/${input.siteId}/clients/${mac}/events`;
  const sessionsPath = `/sites/${input.siteId}/clients/sessions/search`;
  const marvisPath = `/orgs/${input.orgId}/troubleshoot`;

  const [statsRes, searchRes, eventsRes, sessionsRes, marvisRes, devicesRes, apsRes] = await Promise.allSettled([
    mistGet(input.host, input.token, statsPath),
    mistGet(input.host, input.token, searchPath, {
      mac,
      duration: input.duration,
      limit: 20,
    }),
    mistGet(input.host, input.token, eventsPath, {
      duration: input.duration,
      limit: 100,
    }),
    mistGet(input.host, input.token, sessionsPath, {
      mac,
      duration: input.duration,
      limit: 100,
    }),
    mistGet(input.host, input.token, marvisPath, {
      mac: colonMac,
      site_id: input.siteId,
    }),
    mistGet(input.host, input.token, `/sites/${input.siteId}/stats/devices`, { type: "ap" }),
    mistGet(input.host, input.token, `/sites/${input.siteId}/devices`, { type: "ap" }),
  ]);

  const hardFail = [statsRes, searchRes, eventsRes].find(
    (r) => r.status === "rejected" && /401|403|rate limit|timed out/i.test(String((r as PromiseRejectedResult).reason)),
  ) as PromiseRejectedResult | undefined;
  if (hardFail) throw hardFail.reason;

  let stats: ClientStats | null = null;
  if (statsRes.status === "fulfilled") {
    const rec = asRecord(statsRes.value);
    if (rec && rec.mac) stats = pickStats(rec);
    else {
      const arr = asArray(statsRes.value);
      if (arr[0]) stats = pickStats(arr[0]);
    }
  }

  const sightings: ClientStats[] = [];
  if (searchRes.status === "fulfilled") {
    for (const row of asArray(searchRes.value)) {
      sightings.push(pickStats(row));
    }
  }
  if (!stats && sightings[0]) stats = sightings[0];

  const events: ClientEvent[] = [];
  if (eventsRes.status === "fulfilled") {
    for (const row of asArray(eventsRes.value)) events.push(pickEvent(row));
  }
  events.sort((a, b) => b.timestamp - a.timestamp);

  const sessions: ClientSession[] = [];
  if (sessionsRes.status === "fulfilled") {
    for (const row of asArray(sessionsRes.value)) sessions.push(pickSession(row));
  }
  let sessPage = 2;
  while (sessions.length >= 100 * (sessPage - 1) && sessPage <= 5) {
    try {
      const extra = asArray(
        await mistGet(input.host, input.token, sessionsPath, {
          mac,
          duration: input.duration,
          limit: 100,
          page: sessPage,
        }),
      );
      if (!extra.length) break;
      for (const row of extra) sessions.push(pickSession(row));
      if (extra.length < 100) break;
      sessPage += 1;
    } catch {
      break;
    }
  }
  const seenSess = new Set<string>();
  const uniqSess: ClientSession[] = [];
  for (const s of sessions) {
    const key = `${hexMac(s.ap)}|${s.connect}|${s.disconnect}`;
    if (seenSess.has(key)) continue;
    seenSess.add(key);
    uniqSess.push(s);
  }
  uniqSess.sort((a, b) => (b.connect ?? 0) - (a.connect ?? 0));
  sessions.length = 0;
  sessions.push(...uniqSess);

  let marvisText: string | null = null;
  let marvisUnavailable = false;
  let marvisRaw: unknown = null;
  if (marvisRes.status === "fulfilled") {
    const v = marvisRes.value;
    marvisRaw = v;
    if (v == null) marvisUnavailable = true;
    else if (typeof v === "string") marvisText = v;
    else {
      try {
        marvisText = JSON.stringify(v, null, 2);
      } catch {
        marvisText = String(v);
      }
    }
  } else {
    marvisUnavailable = true;
  }

  const inventory = mergeInventory(
    devicesRes.status === "fulfilled" ? devicesRes.value : null,
    apsRes.status === "fulfilled" ? apsRes.value : null,
  );

  attachApNames(sessions, inventory);

  const clientAps = expandClientAps(sessions, events, stats, inventory);
  const families = inventory.map(deviceRadioMacs).filter((g) => g.size);
  const [apSettled, rrmSettled] = await Promise.allSettled([
    fetchApRadio(
      input.host,
      input.token,
      input.siteId,
      stats,
      events,
      sessions,
      marvisRaw ?? marvisText,
      inventory,
    ),
    fetchSiteRrmEvents(
      input.host,
      input.token,
      input.siteId,
      input.duration,
      clientAps,
      families,
      Boolean(input.live),
    ),
  ]);

  let apRadio: ApRadio | null = null;
  if (apSettled.status === "fulfilled") {
    apRadio = apSettled.value;
  } else {
    apRadio = {
      apMac: hexMac(stats?.ap),
      apName: "",
      apNameHint: "",
      source: "unknown",
      dwellSeconds: 0,
      dwellShare: 0,
      bandHint: String(stats?.band ?? "5"),
      marvisMentioned: false,
      marvisAps: [],
      marvisName: null,
      deviceId: "",
      selectionNote: "",
      fallback: true,
      status: "unknown",
      band: "5",
      radio: null,
      channels: [],
      scope: "ap",
      unavailable: apSettled.reason instanceof Error ? apSettled.reason.message : "AP radio lookup failed.",
    };
  }

  const radioPack =
    rrmSettled.status === "fulfilled"
      ? rrmSettled.value
      : { events: [] as RadioEvent[], error: rrmSettled.reason instanceof Error ? rrmSettled.reason.message : "RRM fetch failed", store: buildRadioStore([], clientAps, families) };
  const radioEvents = radioPack.events;
  const radioEventsUnavailable = radioPack.error;
  const radioStore = radioPack.store;
  attachApNames(radioEvents, inventory);
  annotateRadioEvents(radioEvents, events, sessions, stats);
  const clientRadarEvents = radioStore.clientRadarEvents(sessions);
  const clientKeys = new Set(clientRadarEvents.map((e) => `${e.ap}|${e.timestamp}|${e.event}`));
  for (const re of radioEvents) {
    if (clientKeys.has(`${re.ap}|${re.timestamp}|${re.event}`)) {
      re.onClientAp = true;
      if (re.event.toLowerCase().includes("radar")) re.highlight = true;
    }
  }
  for (const re of clientRadarEvents) {
    re.onClientAp = true;
    re.highlight = true;
  }

  let calls: CollabCall[] = [];
  let callsUnavailable: string | null = null;
  try {
    const callPayload = await mistGet(input.host, input.token, `/sites/${input.siteId}/stats/calls/search`, {
      mac,
      duration: RADIO_EVENTS_DURATION,
      limit: 50,
    });
    calls = asArray(callPayload).map(pickCall);
  } catch (err) {
    callsUnavailable = err instanceof Error ? err.message : "calls unavailable";
  }
  calls.sort((a, b) => (b.start ?? 0) - (a.start ?? 0));
  const radarAlerts = radarSessionAlerts(radioEvents, sessions, calls, apRadio, radioStore);

  const lastSeen = stats?.lastSeen ?? null;
  const online = lastSeen != null ? Date.now() / 1000 - lastSeen < 300 : false;

  return {
    demo: false,
    host: input.host,
    orgId: input.orgId,
    siteId: input.siteId,
    siteName: input.siteName,
    mac,
    duration: input.duration,
    online,
    stats,
    sightings,
    events,
    sessions,
    marvisText,
    marvisUnavailable,
    apRadio,
    radioEvents,
    radioEventsUnavailable,
    clientRadarEvents,
    calls,
    callsUnavailable,
    radarAlerts,
    radioStoreStats: {
      scanned: radioStore.scanned,
      dropped: radioStore.dropped,
      radars: radioStore.radars.length,
      kept: radioStore.kept.length,
      clientHits: clientRadarEvents.length,
    },
    verdict: buildVerdict(stats, events, sessions, apRadio, radioEvents, calls, radioStore),
    fetchedAt: Date.now(),
  };
}

async function rrmEventsPage(
  host: MistHost,
  token: string,
  siteId: string,
  band: string,
  page: number,
  start: number,
  end: number,
): Promise<{ rows: Record<string, unknown>[]; hasMore: boolean; error: string | null }> {
  const query: Record<string, string | number> = {
    band,
    start,
    end,
    limit: 100,
    page,
  };
  try {
    const payload = await mistGet(host, token, `/sites/${siteId}/rrm/events`, query);
    const rows = asArray(payload);
    const rec = asRecord(payload);
    const hasMore = Boolean(rec?.next) || rows.length >= 100;
    return { rows, hasMore, error: null };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("400")) {
      try {
        const retry = await mistGet(host, token, `/sites/${siteId}/rrm/events`, query);
        const rows = asArray(retry);
        const rec = asRecord(retry);
        return { rows, hasMore: Boolean(rec?.next) || rows.length >= 100, error: null };
      } catch (err2) {
        return { rows: [], hasMore: false, error: err2 instanceof Error ? err2.message : String(err2) };
      }
    }
    return { rows: [], hasMore: false, error: msg };
  }
}

async function fetchSiteRrmEvents(
  host: MistHost,
  token: string,
  siteId: string,
  duration: DurationKey | string = "1d",
  clientAps?: Set<string>,
  families?: Set<string>[],
  live = false,
): Promise<{ events: RadioEvent[]; error: string | null; store: ReturnType<typeof buildRadioStore> }> {
  const store = buildRadioStore([], clientAps, families);
  const slices = rrmTimeSlices(live ? "1h" : duration);
  const adapt = !live && durationSeconds(duration) >= 86400;
  const pullSlice = async (band: string, pages: number, start: number, end: number, adaptive: boolean) => {
    const local: Record<string, unknown>[] = [];
    let err: string | null = null;
    const cap = adaptive && String(band) === "5" ? RRM_PAGES_ADAPT_5 : pages;
    let clientInSlice = 0;
    for (let page = 1; page <= cap; page++) {
      const { rows, hasMore, error } = await rrmEventsPage(host, token, siteId, band, page, start, end);
      if (error) {
        err = error;
        break;
      }
      local.push(...rows);
      let pageClient = 0;
      for (const raw of rows) {
        const kind = store.add(pickRrmEvent(raw));
        if (kind === "client" || kind === "radar-client") {
          pageClient += 1;
          clientInSlice += 1;
        }
      }
      if (!hasMore) break;
      let oldest = 0;
      for (const r of rows) {
        const t = Number(r.timestamp) || 0;
        const s = Math.abs(t) >= 1e11 ? t / 1000 : t;
        oldest = oldest === 0 ? s : Math.min(oldest, s);
      }
      if (oldest && oldest < start - 60) break;
      if (page >= pages && pageClient === 0 && clientInSlice > 0) break;
    }
    return { local, err, band };
  };
  const jobs: Promise<{ local: Record<string, unknown>[]; err: string | null; band: string }>[] = [];
  const durKey = live ? "1h" : duration;
  for (const [start, end] of slices) {
    const pages5 = live ? RRM_PAGES_LIVE_5 : rrmPagesForBand("5", durKey);
    jobs.push(pullSlice("5", pages5, start, end, adapt));
  }
  if (slices[0]) {
    const [start, end] = slices[0];
    const otherPages = live ? RRM_PAGES_LIVE_OTHER : rrmPagesForBand("24", durKey);
    jobs.push(pullSlice("24", otherPages, start, end, false));
    jobs.push(pullSlice("6", otherPages, start, end, false));
  }
  const results = await Promise.all(jobs);
  const errors: string[] = [];
  for (const block of results) {
    if (block.band === "5" && block.err && !block.local.length) errors.push(`band=5: ${block.err}`);
  }
  const uniq = store.exportEvents();
  if (uniq.length) return { events: uniq, error: null, store };
  return { events: [], error: errors.length ? errors.join("; ") : null, store };
}

async function fetchApRadio(
  host: MistHost,
  token: string,
  siteId: string,
  stats: ClientStats | null,
  events: ClientEvent[],
  sessions: ClientSession[],
  marvis: unknown,
  inventory: Record<string, unknown>[],
): Promise<ApRadio> {
  const picked = pickDominantAp(sessions, stats, events, marvis, inventory);
  const { matchedDev, ...rest } = picked;
  const apMac0 = picked.apMac;
  const empty = (unavailable: string): ApRadio => ({
    ...rest,
    apName: rest.apNameHint || rest.marvisName || (apMac0 ? formatMac(apMac0) : ""),
    status: "unknown",
    band: rest.bandHint || "5",
    radio: null,
    channels: [],
    scope: "ap",
    unavailable,
  });
  if (!apMac0 && !matchedDev) {
    return empty("No AP from Marvis, sessions, events, or live stats.");
  }

  let dev: Record<string, unknown> | null = null;
  if (matchedDev && asRecord(matchedDev.radio_stat)) {
    dev = matchedDev;
  } else {
    const did = String(picked.deviceId || mistDeviceId(apMac0));
    if (did) {
      const rec = asRecord(await mistGet(host, token, `/sites/${siteId}/stats/devices/${did}`));
      if (rec && (!rec.mac || !apMac0 || hexMac(rec.mac) === hexMac(apMac0))) {
        rec.id = rec.id ?? did;
        dev = rec;
      }
    }
    if (!dev && matchedDev) dev = matchedDev;
  }
  if (!dev) {
    return empty(`AP ${picked.marvisName || picked.apNameHint || apMac0 || "—"} not found in site inventory.`);
  }

  const apMac = hexMac(dev.mac) || apMac0;
  const [radioRaw, band] = radioFromDevice(dev, picked.bandHint || "5");
  const servingCh = radioRaw.channel ?? stats?.channel;
  let rrmRows: Record<string, unknown>[] = [];
  const dids: string[] = [];
  for (const cand of [dev.id, picked.deviceId, mistDeviceId(apMac)]) {
    const s = String(cand ?? "").trim();
    if (s && !dids.includes(s)) dids.push(s);
  }
  for (const did of dids) {
    try {
      const rrm = await mistGet(host, token, `/sites/${siteId}/rrm/current/devices/${did}/band/${band}`);
      rrmRows = rrmRowsFrom(rrm);
      if (rrmRows.length) break;
    } catch {
      /* keep trying ids */
    }
  }
  const siteCh = siteAirtimeByChannel(inventory, band);
  let channels = channelsFromRrm(
    rrmRows,
    servingCh,
    Object.keys(radioRaw).length ? radioRaw : null,
    band,
    siteCh,
  );
  if (!channels.length && Object.keys(radioRaw).length) {
    channels = [servingChannelRow(radioRaw, servingCh)];
  }
  const radio = Object.keys(radioRaw).length ? liveRadio(radioRaw) : null;
  const status = String(dev.status ?? (dev.last_seen ? "connected" : "unknown"));
  return {
    ...rest,
    apMac,
    apName: String(dev.name ?? picked.marvisName ?? picked.apNameHint ?? formatMac(apMac)),
    deviceId: String(dev.id ?? mistDeviceId(apMac)),
    status,
    band,
    radio,
    channels,
    scope: "ap",
    unavailable: radio || channels.length ? null : "No radio_stat or RRM occupancy for this AP.",
    lastSeen: typeof dev.last_seen === "number" ? dev.last_seen : null,
  };
}

export type { MistOrg };
