import { formatMac, hexMac, mistDeviceId } from "./mac.ts";
import type { ClientEvent, ClientSession, ClientStats, DominantAp } from "./types.ts";

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

export function foldToken(s: string): string {
  return (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function looksLikeMac(s: string): string {
  const h = hexMac(s);
  return h.length === 12 ? h : "";
}

function nameMacSuffix(name: string): string {
  const folded = foldToken(name);
  const m = folded.match(/[0-9a-f]{6}$/);
  return m ? m[0] : "";
}

function cleanApToken(raw: string): string {
  return raw.replace(/[.,;:!?'"()[\]]+$/g, "").replace(/^["']+|["']+$/g, "").trim();
}

export function marvisTexts(marvis: unknown): string[] {
  if (marvis == null) return [];
  if (typeof marvis === "string") {
    const blob = marvis.trim();
    if (!blob) return [];
    if (blob.startsWith("{") || blob.startsWith("[")) {
      try {
        return marvisTexts(JSON.parse(blob));
      } catch {
        return [marvis];
      }
    }
    return [marvis];
  }
  const texts: string[] = [];
  const obj = marvis;
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    const rec = obj as Record<string, unknown>;
    for (const row of asArray(rec.results ?? rec.insights ?? rec.data)) {
      for (const k of ["text", "description", "reason", "recommendation", "message"]) {
        if (row[k]) texts.push(String(row[k]));
      }
      if (row.ap) texts.push(`connected to ${row.ap}`);
      if (row.ap_name) texts.push(`connected to ${row.ap_name} most of the time`);
    }
    for (const k of ["text", "description", "reason", "recommendation"]) {
      if (rec[k]) texts.push(String(rec[k]));
    }
  } else if (Array.isArray(obj)) {
    for (const row of obj) {
      if (row && typeof row === "object" && (row as Record<string, unknown>).text) {
        texts.push(String((row as Record<string, unknown>).text));
      } else if (typeof row === "string") texts.push(row);
    }
  }
  return texts;
}

export function parseMarvisApHints(marvis: unknown): {
  mostName: string | null;
  names: string[];
  macs: string[];
  texts: string[];
  blob: string;
} {
  const texts = marvisTexts(marvis);
  const blob = texts.join("\n");
  let mostName: string | null = null;
  const names: string[] = [];
  const macs: string[] = [];

  function addName(raw: string, most = false) {
    const cand = cleanApToken(raw);
    if (!cand) return;
    if (most && !mostName) mostName = cand;
    if (!names.includes(cand)) names.push(cand);
    const h = looksLikeMac(cand);
    if (h && !macs.includes(h)) macs.push(h);
  }

  const mostRe = /connected to\s+(.+?)\s+most of the time/gi;
  let m: RegExpExecArray | null;
  while ((m = mostRe.exec(blob))) addName(m[1], true);
  const anyRe =
    /(?:was connected to|connected to|associated to|roamed to|on AP)\s+([A-Za-z0-9][A-Za-z0-9._:-]{2,80})/gi;
  while ((m = anyRe.exec(blob))) addName(m[1]);
  const macRe = /(?:[0-9a-f]{2}[:\-]){5}[0-9a-f]{2}|[0-9a-f]{12}/gi;
  while ((m = macRe.exec(blob))) {
    const h = hexMac(m[0]);
    if (h.length === 12 && !macs.includes(h)) macs.push(h);
  }
  return { mostName, names, macs, texts, blob };
}

export function matchInventory(
  inventory: Record<string, unknown>[],
  opts: { name?: string; mac?: string; text?: string } = {},
): Record<string, unknown> | null {
  if (!inventory.length) return null;
  const macH = hexMac(opts.mac ?? "");
  const nameN = (opts.name ?? "").trim();
  const nameF = foldToken(nameN);
  let suf = nameN ? nameMacSuffix(nameN) : "";
  if (macH.length >= 6 && !suf) suf = macH.slice(-6);
  const blob = opts.text ?? "";
  const blobL = blob.toLowerCase();
  const blobF = foldToken(blob);

  function score(dev: Record<string, unknown>): number {
    const dmac = hexMac(dev.mac);
    const dname = String(dev.name ?? "").trim();
    const dn = dname.toLowerCase();
    const df = foldToken(dname);
    let s = 0;
    if (macH && dmac === macH) s += 100;
    if (nameF && df === nameF) s += 90;
    if (nameN && dn === nameN.toLowerCase()) s += 90;
    if (nameF && df && (nameF.includes(df) || df.includes(nameF)) && Math.min(nameF.length, df.length) >= 8) s += 50;
    if (blob && dname && dname.length >= 4 && blobL.includes(dn)) s += 80;
    if (blobF && df && df.length >= 8 && blobF.includes(df)) s += 80;
    const dsuf = nameMacSuffix(dname);
    if (suf.length >= 6 && (dmac.endsWith(suf) || dsuf === suf)) s += 75;
    if (blobF && dmac.length === 12 && blobF.includes(dmac)) s += 70;
    if (blobF && dmac.length >= 6 && dmac.slice(-6) && blobF.includes(dmac.slice(-6)) && dsuf && blobF.includes(dsuf)) {
      s += 65;
    }
    return s;
  }

  const ranked = inventory.map((d) => [score(d), d] as const).sort((a, b) => b[0] - a[0]);
  if (ranked[0] && ranked[0][0] >= 65) return ranked[0][1];
  return null;
}

export function pickDominantAp(
  sessions: ClientSession[],
  stats: ClientStats | null,
  events: ClientEvent[],
  marvis: unknown,
  inventory: Record<string, unknown>[] = [],
): DominantAp & { matchedDev: Record<string, unknown> | null } {
  const hints = parseMarvisApHints(marvis);
  const dwell: Record<string, number> = {};
  for (const s of sessions) {
    const ap = hexMac(s.ap);
    if (!ap) continue;
    dwell[ap] = (dwell[ap] ?? 0) + Number(s.duration ?? 0);
  }

  let source = "";
  let apMac = "";
  let apName = String(hints.mostName ?? "");
  let matched: Record<string, unknown> | null = null;
  let marvisUnmatched = "";
  const blob = hints.blob;

  if (hints.mostName || hints.names.length || hints.macs.length || blob) {
    if (hints.mostName) matched = matchInventory(inventory, { name: hints.mostName, text: blob });
    if (!matched) matched = matchInventory(inventory, { text: blob });
    if (!matched) {
      for (const n of hints.names) {
        matched = matchInventory(inventory, { name: n, text: blob });
        if (matched) break;
      }
    }
    if (!matched) {
      for (const m of hints.macs) {
        matched = matchInventory(inventory, { mac: m });
        if (matched) break;
      }
    }
    if (matched) {
      apMac = hexMac(matched.mac);
      apName = String(matched.name ?? apName);
      source = "marvis";
    } else if (hints.macs.length) {
      apMac = hints.macs[0];
      source = "marvis";
      apName = apName || String(hints.mostName ?? "");
    } else if (hints.mostName || hints.names.length) {
      marvisUnmatched = String(hints.mostName || hints.names[0]);
    }
  }

  let fallbackFrom = "";
  if (!apMac && Object.keys(dwell).length) {
    apMac = Object.entries(dwell).sort((a, b) => b[1] - a[1])[0][0];
    source = "sessions";
    fallbackFrom = "longest-session";
    matched = matchInventory(inventory, { mac: apMac }) ?? matched;
    if (matched) apName = String(matched.name ?? apName);
  }
  if (!apMac) {
    const counts: Record<string, number> = {};
    for (const e of events) {
      const ap = hexMac(e.ap);
      if (ap) counts[ap] = (counts[ap] ?? 0) + 1;
    }
    const entries = Object.entries(counts);
    if (entries.length) {
      apMac = entries.sort((a, b) => b[1] - a[1])[0][0];
      source = "events";
      fallbackFrom = "event-count";
      matched = matchInventory(inventory, { mac: apMac }) ?? matched;
      if (matched) apName = String(matched.name ?? apName);
    }
  }
  if (!apMac) {
    apMac = hexMac(stats?.ap);
    source = "stats";
    fallbackFrom = "live client stats";
    matched = matchInventory(inventory, { mac: apMac }) ?? matched;
    if (matched) apName = String(matched.name ?? apName);
  }

  const total = Object.values(dwell).reduce((a, b) => a + b, 0) || 1;
  let band = "";
  for (const s of sessions) {
    if (hexMac(s.ap) === apMac && s.band) {
      band = String(s.band);
      break;
    }
  }
  if (!band) band = String(stats?.band ?? "5");

  const pretty = apName || (apMac ? formatMac(apMac) : "—");
  let selectionNote: string;
  if (source === "marvis") {
    const named = hints.mostName || pretty;
    selectionNote = `Marvis named ${named} as the AP this client used most of the time. Chart is that radio (${formatMac(apMac)}).`;
  } else if (marvisUnmatched) {
    selectionNote = `Marvis named ${marvisUnmatched}, but that name did not match a site AP in inventory. Chart is the ${fallbackFrom || "longest-session"} AP ${pretty}.`;
  } else if (hints.texts.length) {
    selectionNote = `Marvis did not name a recognizable site AP. Chart is the ${fallbackFrom || "longest-session"} AP ${pretty}.`;
  } else {
    selectionNote = `Marvis Troubleshoot did not return an AP name. Chart is the ${fallbackFrom || "longest-session"} AP ${pretty}.`;
  }

  return {
    apMac,
    apNameHint: apName,
    source: source || "unknown",
    dwellSeconds: apMac ? (dwell[apMac] ?? 0) : 0,
    dwellShare: apMac && Object.keys(dwell).length ? (dwell[apMac] ?? 0) / total : 0,
    bandHint: band,
    marvisMentioned: source === "marvis",
    marvisAps: [...hints.macs],
    marvisName: hints.mostName || apName || null,
    deviceId: String(matched?.id ?? (apMac ? mistDeviceId(apMac) : "")),
    selectionNote,
    fallback: source !== "marvis",
    matchedDev: matched,
  };
}

export function mergeInventory(
  statsDevices: unknown,
  devices: unknown,
): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const seen = new Set<string>();
  function add(rows: Record<string, unknown>[]) {
    for (const d of rows) {
      const typ = String(d.type ?? "ap").toLowerCase();
      if (typ && typ !== "ap" && typ !== "access-point") continue;
      const mac = hexMac(d.mac);
      const key = mac || String(d.id ?? d.name ?? "");
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(d);
    }
  }
  add(asArray(statsDevices));
  const byMac = new Map(out.map((d) => [hexMac(d.mac), d] as const).filter(([m]) => m));
  for (const d of asArray(devices)) {
    const m = hexMac(d.mac);
    const hit = m ? byMac.get(m) : undefined;
    if (hit) {
      if (d.name && !hit.name) hit.name = d.name;
      if (d.id && !hit.id) hit.id = d.id;
    } else if (m && !seen.has(m)) {
      seen.add(m);
      out.push(d);
      byMac.set(m, d);
    }
  }
  return out;
}
