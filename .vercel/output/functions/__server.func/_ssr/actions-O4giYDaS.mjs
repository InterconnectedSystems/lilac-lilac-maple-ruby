import { n as TSS_SERVER_FUNCTION, t as createServerFn } from "./ssr.mjs";
import { a as formatMac, c as pickEvent, l as pickSession, n as MIST_HOSTS, o as isMistHost, r as buildVerdict, s as normalizeMac, u as pickStats } from "./mac-7PhnM4gV.mjs";
import { a as string, i as object, t as _enum } from "../_libs/zod.mjs";
//#region node_modules/.nitro/vite/services/ssr/assets/actions-O4giYDaS.js
var createServerRpc = (serverFnMeta, splitImportFn) => {
	const url = "/_serverFn/" + serverFnMeta.id;
	return Object.assign(splitImportFn, {
		url,
		serverFnMeta,
		[TSS_SERVER_FUNCTION]: true
	});
};
var TIMEOUT_MS = 25e3;
function stripTokenPrefix(token) {
	return token.replace(/^token\s+/i, "").trim();
}
async function mistGet(host, token, path, params) {
	if (!isMistHost(host)) throw new Error("Host is not a known Mist API region.");
	const url = new URL(`https://${host}/api/v1${path}`);
	if (params) {
		for (const [k, v] of Object.entries(params)) if (v !== void 0 && v !== "") url.searchParams.set(k, String(v));
	}
	const ctrl = new AbortController();
	const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
	try {
		const res = await fetch(url, {
			method: "GET",
			headers: {
				Authorization: `Token ${stripTokenPrefix(token)}`,
				Accept: "application/json"
			},
			signal: ctrl.signal
		});
		if (res.status === 204) return null;
		if (res.status === 401) throw new Error("Token rejected (401). Check region and token.");
		if (res.status === 403) throw new Error("Token lacks permission for this org or site (403).");
		if (res.status === 404) return null;
		if (res.status === 429) throw new Error("Mist rate limit (429). Wait a minute and retry.");
		if (!res.ok) {
			const body = await res.text().catch(() => "");
			throw new Error(`Mist API ${res.status}: ${body.slice(0, 180) || res.statusText}`);
		}
		const text = await res.text();
		if (!text) return null;
		return JSON.parse(text);
	} catch (err) {
		if (err instanceof Error && err.name === "AbortError") throw new Error("Mist API timed out after 25s.");
		throw err;
	} finally {
		clearTimeout(timer);
	}
}
function asRecord(v) {
	return v && typeof v === "object" && !Array.isArray(v) ? v : null;
}
function asArray(v) {
	if (Array.isArray(v)) return v.filter((x) => x && typeof x === "object");
	const rec = asRecord(v);
	if (rec && Array.isArray(rec.results)) return rec.results.filter((x) => x && typeof x === "object");
	return [];
}
async function connectMist(input) {
	const self = asRecord(await mistGet(input.host, input.token, "/self"));
	if (!self) throw new Error("Empty /self response.");
	const orgs = /* @__PURE__ */ new Map();
	const privileges = Array.isArray(self.privileges) ? self.privileges : [];
	for (const p of privileges) {
		const rec = asRecord(p);
		if (!rec) continue;
		if (rec.scope === "org" && typeof rec.org_id === "string") orgs.set(rec.org_id, String(rec.name ?? rec.org_id));
	}
	if (typeof self.org_id === "string" && !orgs.has(self.org_id)) orgs.set(self.org_id, String(self.name ?? self.org_id));
	if (orgs.size === 0) throw new Error("No organization privileges on this token.");
	return {
		email: String(self.email ?? self.name ?? "API token"),
		orgs: [...orgs.entries()].map(([id, name]) => ({
			id,
			name
		}))
	};
}
async function listSites(input) {
	const sites = asArray(await mistGet(input.host, input.token, `/orgs/${input.orgId}/sites`)).map((r) => ({
		id: String(r.id ?? ""),
		name: String(r.name ?? r.id ?? "Unnamed")
	})).filter((s) => s.id);
	sites.sort((a, b) => a.name.localeCompare(b.name));
	if (!sites.length) {
		const self = asRecord(await mistGet(input.host, input.token, "/self"));
		const privileges = Array.isArray(self?.privileges) ? self.privileges : [];
		for (const p of privileges) {
			const rec = asRecord(p);
			if (rec?.scope === "site" && rec.org_id === input.orgId && typeof rec.site_id === "string") sites.push({
				id: rec.site_id,
				name: String(rec.name ?? rec.site_id)
			});
		}
	}
	if (!sites.length) throw new Error("No sites visible for this org/token.");
	return sites;
}
async function diagnoseClient(input) {
	const mac = normalizeMac(input.mac);
	const colonMac = formatMac(mac);
	const statsPath = `/sites/${input.siteId}/stats/clients/${mac}`;
	const searchPath = `/sites/${input.siteId}/clients/search`;
	const eventsPath = `/sites/${input.siteId}/clients/${mac}/events`;
	const sessionsPath = `/sites/${input.siteId}/clients/sessions/search`;
	const marvisPath = `/orgs/${input.orgId}/troubleshoot`;
	const [statsRes, searchRes, eventsRes, sessionsRes, marvisRes] = await Promise.allSettled([
		mistGet(input.host, input.token, statsPath),
		mistGet(input.host, input.token, searchPath, {
			mac,
			duration: input.duration,
			limit: 20
		}),
		mistGet(input.host, input.token, eventsPath, {
			duration: input.duration,
			limit: 100
		}),
		mistGet(input.host, input.token, sessionsPath, {
			mac,
			duration: input.duration,
			limit: 50
		}),
		mistGet(input.host, input.token, marvisPath, {
			mac: colonMac,
			site_id: input.siteId
		})
	]);
	const hardFail = [
		statsRes,
		searchRes,
		eventsRes
	].find((r) => r.status === "rejected" && /401|403|rate limit|timed out/i.test(String(r.reason)));
	if (hardFail) throw hardFail.reason;
	let stats = null;
	if (statsRes.status === "fulfilled") {
		const rec = asRecord(statsRes.value);
		if (rec && rec.mac) stats = pickStats(rec);
		else {
			const arr = asArray(statsRes.value);
			if (arr[0]) stats = pickStats(arr[0]);
		}
	}
	const sightings = [];
	if (searchRes.status === "fulfilled") for (const row of asArray(searchRes.value)) sightings.push(pickStats(row));
	if (!stats && sightings[0]) stats = sightings[0];
	const events = [];
	if (eventsRes.status === "fulfilled") for (const row of asArray(eventsRes.value)) events.push(pickEvent(row));
	events.sort((a, b) => b.timestamp - a.timestamp);
	const sessions = [];
	if (sessionsRes.status === "fulfilled") for (const row of asArray(sessionsRes.value)) sessions.push(pickSession(row));
	let marvisText = null;
	let marvisUnavailable = false;
	if (marvisRes.status === "fulfilled") {
		const v = marvisRes.value;
		if (v == null) marvisUnavailable = true;
		else if (typeof v === "string") marvisText = v;
		else try {
			marvisText = JSON.stringify(v, null, 2);
		} catch {
			marvisText = String(v);
		}
	} else marvisUnavailable = true;
	const lastSeen = stats?.lastSeen ?? null;
	const online = lastSeen != null ? Date.now() / 1e3 - lastSeen < 300 : false;
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
		verdict: buildVerdict(stats, events, sessions),
		fetchedAt: Date.now()
	};
}
var creds = object({
	token: string().min(8).max(512),
	host: _enum(MIST_HOSTS)
});
var mistConnect_createServerFn_handler = createServerRpc({
	id: "7725acdc32a8050a231a8a2a336509d2da6812591dae88b605fc06c4c61f5a5d",
	name: "mistConnect",
	filename: "src/lib/mist/actions.ts"
}, (opts) => mistConnect.__executeServer(opts));
var mistConnect = createServerFn({ method: "POST" }).validator(creds).handler(mistConnect_createServerFn_handler, async ({ data }) => connectMist(data));
var mistListSites_createServerFn_handler = createServerRpc({
	id: "41a8a3b62e44385ad046bffbed933123de76d1638e4aee370e40e6a518247b8d",
	name: "mistListSites",
	filename: "src/lib/mist/actions.ts"
}, (opts) => mistListSites.__executeServer(opts));
var mistListSites = createServerFn({ method: "POST" }).validator(creds.extend({ orgId: string().min(4).max(80) })).handler(mistListSites_createServerFn_handler, async ({ data }) => listSites(data));
var mistDiagnose_createServerFn_handler = createServerRpc({
	id: "f14837cc7d50bd2bc49c6433a5b7809c549e88bbb483ffc035eaba246ed4c847",
	name: "mistDiagnose",
	filename: "src/lib/mist/actions.ts"
}, (opts) => mistDiagnose.__executeServer(opts));
var mistDiagnose = createServerFn({ method: "POST" }).validator(creds.extend({
	orgId: string().min(4).max(80),
	siteId: string().min(4).max(80),
	siteName: string().max(120),
	mac: string().min(12).max(32),
	duration: _enum([
		"1h",
		"6h",
		"1d",
		"1w"
	])
})).handler(mistDiagnose_createServerFn_handler, async ({ data }) => diagnoseClient(data));
//#endregion
export { mistConnect_createServerFn_handler, mistDiagnose_createServerFn_handler, mistListSites_createServerFn_handler };
