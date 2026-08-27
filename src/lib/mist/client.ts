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
import type {
  ApRadio,
  ClientEvent,
  ClientSession,
  ClientStats,
  ConnectResult,
  DiagnoseResult,
  DurationKey,
  MistOrg,
  MistSite,
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
      limit: 50,
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

  let apRadio: ApRadio | null = null;
  try {
    apRadio = await fetchApRadio(
      input.host,
      input.token,
      input.siteId,
      stats,
      events,
      sessions,
      marvisRaw ?? marvisText,
      inventory,
    );
  } catch (err) {
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
      unavailable: err instanceof Error ? err.message : "AP radio lookup failed.",
    };
  }

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
    verdict: buildVerdict(stats, events, sessions, apRadio),
    fetchedAt: Date.now(),
  };
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
