import assert from "node:assert/strict";
import test from "node:test";
import { buildCorrelations } from "./correlate.ts";
import { buildVerdict, pickEvent } from "./classify.ts";
import type { ClientEvent, ClientSession, ClientStats } from "./types.ts";

function ev(partial: Partial<ClientEvent> & Pick<ClientEvent, "type" | "timestamp">): ClientEvent {
  return pickEvent({
    ...partial,
    text: partial.text ?? "",
    ap: partial.ap ?? "aa",
    ssid: partial.ssid ?? "corp",
    band: partial.band ?? "5",
    reason: partial.reason ?? null,
  });
}

const baseStats: ClientStats = {
  mac: "aabbccddeeff",
  hostname: "host",
  manufacture: "Apple",
  os: null,
  model: null,
  ssid: "corp",
  vlan: 40,
  ip: "10.0.0.2",
  ap: "ap1",
  band: "5",
  channel: 149,
  proto: "ax",
  rssi: -81,
  snr: 11,
  txRate: 58,
  rxRate: 48,
  uptime: 200,
  lastSeen: 1,
  txBytes: 1,
  rxBytes: 1,
  username: null,
  keyMgmt: "WPA2-PSK",
  txRetries: 200,
  rxRetries: 10,
  dualBand: true,
};

test("weak RSSI+SNR plus DHCP after assoc correlates as coverage and L3", () => {
  const t = 1_000_000;
  const events = [
    ev({ timestamp: t - 90, type: "CLIENT_DHCP_TIMED_OUT", text: "no ACK", ap: "ap2" }),
    ev({ timestamp: t - 140, type: "CLIENT_ASSOCIATION", text: "Associated", ap: "ap2" }),
    ev({ timestamp: t - 148, type: "CLIENT_DEAUTHENTICATION", text: "idle", ap: "ap1", reason: 4 }),
    ev({ timestamp: t - 420, type: "CLIENT_DEAUTHENTICATION", text: "4-way handshake timeout", ap: "ap1", reason: 15 }),
  ];
  const cors = buildCorrelations(baseStats, events, [
    { ap: "ap1", ssid: "corp", band: "5", connect: t - 480, disconnect: t - 148, duration: 28 },
    { ap: "ap1", ssid: "corp", band: "5", connect: t - 900, disconnect: t - 840, duration: 44 },
  ]);
  const keys = cors.map((c) => c.id.replace(/-\d+$/, ""));
  assert.ok(keys.includes("rf-coverage"), keys.join(","));
  assert.ok(keys.includes("dhcp-after-join"), keys.join(","));
  assert.ok(keys.includes("handshake"), keys.join(","));
  assert.ok(keys.includes("sticky-idle"), keys.join(","));
  const v = buildVerdict(baseStats, events, []);
  assert.ok(v.correlations.length >= 2);
  assert.notEqual(v.primaryCause, "No dominant failure signature — review the timeline.");
  assert.equal("score" in v, false);
  assert.equal("label" in v, false);
});

test("SNR collapse with decent RSSI is tagged as noise, not coverage", () => {
  const cors = buildCorrelations({ ...baseStats, rssi: -62, snr: 8, txRetries: 12 }, [], []);
  assert.equal(cors[0]?.id, "rf-noise");
});

test("healthy empty window has no correlations", () => {
  const v = buildVerdict(null, [], []);
  assert.deepEqual(v.correlations, []);
  assert.equal(v.primaryCause, "No dominant failure signature — review the timeline.");
  assert.equal("score" in v, false);
  assert.equal("label" in v, false);
});

test("successful association is not a negative/auth failure", () => {
  const t = 1_000_000;
  const events = [
    ev({ timestamp: t - 10, type: "CLIENT_ASSOCIATION", text: "Associated", ap: "ap1" }),
    ev({ timestamp: t - 12, type: "CLIENT_AUTHORIZATION", text: "Authorized", ap: "ap1" }),
  ];
  assert.equal(events[0].negative, false);
  assert.equal(events[1].negative, false);
  const v = buildVerdict({ ...baseStats, rssi: -49, snr: 35, txRetries: 10 }, events, []);
  assert.ok(!v.notes.some((n) => n.toLowerCase().includes("authentication/association failure")));
});

test("deauth does not double-count as an auth failure", () => {
  const t = 1_000_000;
  const events = [
    ev({ timestamp: t - 10, type: "CLIENT_DEAUTHENTICATION", text: "Deauthenticated by AP", ap: "ap1", reason: 8 }),
  ];
  const v = buildVerdict({ ...baseStats, rssi: -49, snr: 35, txRetries: 10 }, events, []);
  assert.ok(v.notes.some((n) => n.includes("deauth/disassoc")));
  assert.ok(!v.notes.some((n) => n.toLowerCase().includes("authentication/association failure")));
});

test("high retries with usable RSSI cite CCI / hidden node, not coverage", () => {
  const cors = buildCorrelations(
    { ...baseStats, rssi: -49, snr: 38, txRetries: 271 },
    [],
    [],
  );
  const hit = cors.find((c) => c.id === "retries-rf-ok");
  assert.ok(hit, cors.map((c) => c.id).join(","));
  assert.match(hit!.evidence, /CCI|hidden node|non-Wi-Fi interference/i);
});

test("CLIENT_IP_ASSIGNED is OK, not a DHCP failure", () => {
  const evIp = pickEvent({ type: "CLIENT_IP_ASSIGNED", text: "IP Assigned", timestamp: 1, ap: "ap1" });
  assert.equal(evIp.negative, false);
  const evOk = pickEvent({ type: "CLIENT_DHCP_OK", text: "DHCP Success", timestamp: 1, ap: "ap1" });
  assert.equal(evOk.negative, false);
  const evFail = pickEvent({ type: "CLIENT_DHCP_TIMED_OUT", text: "no ACK", timestamp: 1, ap: "ap1" });
  assert.equal(evFail.negative, true);
});

test("radar on the session AP is highlighted; neighbor radar is not", async () => {
  const { pickRrmEvent, radarSessionAlerts, radioEventCorrelations } = await import("./radio.ts");
  const t = 1_700_000_000;
  const radar = pickRrmEvent({
    timestamp: t - 156,
    ap: "0a0027aa1103",
    event: "rrm-radar",
    channel: 149,
    pre_channel: 36,
    apName: "DEMO-AP-F2-aa:11:03",
  });
  const neighbor = pickRrmEvent({
    timestamp: t - 156,
    ap: "0a0027aa1105",
    event: "rrm-radar",
    channel: 36,
    pre_channel: 36,
    apName: "DEMO-AP-F2-aa:11:05",
  });
  const sess = [
    {
      ap: "0a0027aa1103",
      apName: "DEMO-AP-F2-aa:11:03",
      ssid: "CORP-WIFI",
      band: "5",
      connect: t - 480,
      disconnect: t - 148,
      duration: 332,
    },
  ];
  const events = [
    pickEvent({
      timestamp: t - 148,
      type: "CLIENT_DEAUTHENTICATION",
      text: "Deauthenticated by AP",
      ap: "0a0027aa1103",
      reason: 4,
    }),
  ];
  const alerts = radarSessionAlerts([radar], sess, [], null);
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].sessionAp, alerts[0].radarAp);
  assert.equal(alerts[0].radio.event, "rrm-radar");
  assert.equal(radarSessionAlerts([neighbor], sess, [], null).length, 0);
  const cors = radioEventCorrelations([radar], events, sess, null, null);
  assert.ok(cors[0]?.highlight);
  assert.match(cors[0]!.id, /radio-radar/);
  const miss = radioEventCorrelations([neighbor], events, sess, null, null);
  assert.equal(miss.filter((c) => c.id.startsWith("radio-radar")).length, 0);
});

test("demo investigation includes session-on-radar-AP alert and Teams overlap", async () => {
  const { buildDemoResult } = await import("./demo-data.ts");
  const demo = buildDemoResult();
  assert.ok(demo.radarAlerts.length >= 1, "expected radar session alert");
  assert.equal(demo.radarAlerts[0].sessionAp, demo.radarAlerts[0].radarAp);
  assert.equal(demo.radarAlerts[0].call, "Microsoft Teams");
  assert.ok(demo.sessions.some((s) => s.hitByRadar));
  assert.ok(demo.radioEvents.some((e) => e.event === "rrm-radar" && e.highlight));
  assert.ok((demo.clientRadarEvents?.length ?? 0) >= 1, "expected client radar store rows");
  const ids = demo.verdict.correlations.map((c) => c.id);
  assert.ok(ids.some((i) => i.startsWith("radio-radar")), ids.join(","));
  assert.ok(ids.some((i) => i.startsWith("call-radar")), ids.join(","));
  assert.equal(demo.verdict.correlations[0]?.highlight, true);
  const callRadar = demo.verdict.correlations.find((c) => c.id.startsWith("call-radar"));
  assert.equal(callRadar?.detail?.call, "Microsoft Teams");
  assert.ok(callRadar?.detail?.radarEvent, "call-radar missing radar event detail");
});

test("Teams overlapping same-AP radar stays correlated through the radar store", async () => {
  const { pickCall, pickRrmEvent, RadioEventStore, callCorrelations, radarSessionAlerts } = await import("./radio.ts");
  const t = 1_700_000_000;
  const radar = pickRrmEvent({
    timestamp: t,
    ap: "0a0027aa1103",
    band: "5",
    event: "rrm-radar",
    channel: 149,
    pre_channel: 36,
  });
  const sess = [
    { ap: "0a0027aa1103", ssid: "c", band: "5", connect: t - 60, disconnect: t + 12, duration: 72 },
  ];
  const teams = pickCall({
    app: "teams",
    meeting_id: "m1",
    start_time: t - 20,
    end_time: t + 80,
    audio_quality: 2,
    video_quality: 3,
  });
  const store = new RadioEventStore(["0a0027aa1103"]);
  for (let i = 0; i < 2000; i++) {
    store.add(
      pickRrmEvent({
        timestamp: t - i,
        ap: "0a0027aa11ff",
        band: "5",
        event: "rrm-radar",
        channel: 44,
        pre_channel: 36,
      }),
    );
  }
  store.add(radar);
  const cors = callCorrelations([teams], [], sess, null, store.exportEvents(), null, store);
  const hits = cors.filter((c) => c.id.startsWith("call-radar"));
  assert.equal(hits.length, 1, cors.map((c) => c.id).join(","));
  assert.equal(hits[0]?.detail?.call, "Microsoft Teams");
  assert.equal(hits[0]?.detail?.radarAp, "0a0027aa1103");
  const alerts = radarSessionAlerts(store.exportEvents(), sess, [teams], null, store);
  assert.equal(alerts[0]?.call, "Microsoft Teams");
  const teamsMs = pickCall({
    app: "teams",
    meeting_id: "m-ms",
    start_time: (t - 20) * 1000,
    end_time: (t + 80) * 1000,
    audio_quality: 2,
    video_quality: 3,
  });
  assert.equal(teamsMs.start, t - 20);
  assert.equal(teamsMs.end, t + 80);
  const corsMs = callCorrelations([teamsMs], [], sess, null, [radar], null, null);
  assert.ok(corsMs.some((c) => c.id.startsWith("call-radar")), corsMs.map((c) => c.id).join(","));
});

test("AP-keyed radar store finds the client DFS hit under 2000 neighbor radars", async () => {
  const { pickRrmEvent, RadioEventStore, radarSessionAlerts, radioEventCorrelations } = await import("./radio.ts");
  const t = 1_700_000_000;
  const store = new RadioEventStore(["0a0027aa1103"]);
  const buried = pickRrmEvent({
    timestamp: t - 3600,
    ap: "0a0027aa1103",
    band: "5",
    event: "rrm-radar",
    channel: 149,
    pre_channel: 36,
  });
  for (let i = 0; i < 2000; i++) {
    store.add(
      pickRrmEvent({
        timestamp: t - i,
        ap: "0a0027aa11ff",
        band: "5",
        event: "rrm-radar",
        channel: 44,
        pre_channel: 36,
      }),
    );
  }
  store.add(buried);
  const sess = [{ ap: "0a0027aa1103", ssid: "c", band: "5", connect: t - 86400, disconnect: t, duration: 86400 }];
  assert.equal(store.hitsForSession(sess[0]!).length, 1);
  assert.equal(store.clientRadarEvents(sess).length, 1);
  const exported = store.exportEvents();
  assert.equal(exported.some((e) => e.ap === "0a0027aa11ff"), false);
  assert.ok(store.radarsOnAp("0a0027aa11ff").length >= 1, "neighbor radar stays indexed");
  assert.equal(radarSessionAlerts(exported, sess, [], null, store).length, 1);
  assert.equal(
    radioEventCorrelations(exported, [], sess, null, null, store).filter((c) => c.id.startsWith("radio-radar")).length,
    1,
  );
});

test("BSSID family + disconnect=0 + ap_mac field still alert", async () => {
  const { pickRrmEvent, RadioEventStore, radarSessionAlerts, sessionCovers } = await import("./radio.ts");
  const t = 1_700_000_000;
  const store = new RadioEventStore(["0a0027aa1103"], [new Set(["0a0027aa1100", "0a0027aa1103"])]);
  store.add(
    pickRrmEvent({
      timestamp: t - 10,
      ap_mac: "0a0027aa1100",
      band: "5",
      event: "radar-detected",
      channel: 100,
      pre_channel: 36,
    }),
  );
  const sess = [{ ap: "0a0027aa1103", ssid: "c", band: "5", connect: t - 60, disconnect: 0, duration: null }];
  assert.equal(sessionCovers(sess[0]!, t - 10), true);
  assert.equal(store.hitsForSession(sess[0]!).length, 1);
  assert.equal(radarSessionAlerts(store.exportEvents(), sess, [], null, store).length, 1);
});

test("overlapping duplicate sessions do not print two radar banners", async () => {
  const { pickRrmEvent, RadioEventStore, radarSessionAlerts } = await import("./radio.ts");
  const t = 1_700_000_000;
  const sess: ClientSession[] = [
    {
      ap: "04cdc023a061",
      apName: "ISB05-AP16-A061",
      ssid: "Corporate_Wifi",
      band: "5",
      connect: t - 10266,
      disconnect: t + 1,
      duration: 10267,
    },
    {
      ap: "04cdc023a061",
      apName: "ISB05-AP16-A061",
      ssid: "Corporate_Wifi",
      band: "5",
      connect: t - 10265.6,
      disconnect: t + 1.2,
      duration: 10266.8,
    },
  ];
  const store = new RadioEventStore(["04cdc023a061"]);
  const radar = pickRrmEvent({
    timestamp: t,
    ap: "04cdc023a061",
    band: "5",
    event: "radar-detected",
    channel: 149,
    pre_channel: 56,
    bandwidth: 20,
    power: 6,
    apName: "ISB05-AP16-A061",
  });
  store.add(radar);
  store.add(
    pickRrmEvent({
      timestamp: t,
      ap: "04cdc023a061",
      band: "5",
      event: "radar-detected",
      channel: 149,
      pre_channel: 56,
      bandwidth: 20,
      power: 6,
      apName: "ISB05-AP16-A061",
    }),
  );
  const alerts = radarSessionAlerts([radar], sess, [], null, store);
  assert.equal(alerts.length, 1, JSON.stringify(alerts.map((a) => a.sessionConnect)));
  assert.equal((alerts[0]!.radios ?? []).length, 1);
  assert.equal(store.clientRadarEvents(sess).length, 1);
  assert.ok(sess.every((s) => s.hitByRadar));
  store.add(
    pickRrmEvent({
      timestamp: t - 90,
      ap: "04cdc023a061",
      band: "5",
      event: "rrm-radar",
      channel: 100,
      pre_channel: 56,
      apName: "ISB05-AP16-A061",
    }),
  );
  const two = radarSessionAlerts(store.exportEvents(), sess, [], null, store);
  assert.equal(two.length, 1, JSON.stringify(two.map((a) => a.id)));
  assert.equal((two[0]!.radios ?? []).length, 2);
  const seq = [
    { ap: "04cdc023a061", ssid: "c", band: "5", connect: t - 8000, disconnect: t - 7000, duration: 1000 },
    { ap: "04cdc023a061", ssid: "c", band: "5", connect: t - 2000, disconnect: t - 1000, duration: 1000 },
  ];
  const storeSeq = new RadioEventStore(["04cdc023a061"]);
  storeSeq.add(pickRrmEvent({ timestamp: t - 7500, ap: "04cdc023a061", event: "radar-detected", channel: 36 }));
  storeSeq.add(pickRrmEvent({ timestamp: t - 1500, ap: "04cdc023a061", event: "radar-detected", channel: 100 }));
  assert.equal(radarSessionAlerts(storeSeq.exportEvents(), seq, [], null, storeSeq).length, 2);
});

test("verdict has no health score or Healthy/Degraded/Critical label", async () => {
  const empty = buildVerdict(null, [], []);
  assert.equal("score" in empty, false);
  assert.equal("label" in empty, false);
  assert.equal(empty.primaryCause, "No dominant failure signature — review the timeline.");

  const noisy = buildVerdict(baseStats, [
    ev({ timestamp: 1_000_000, type: "CLIENT_DEAUTHENTICATION", text: "idle", reason: 4 }),
  ], []);
  assert.equal("score" in noisy, false);
  assert.equal("label" in noisy, false);
  assert.ok(noisy.primaryCause.length > 0);

  const { buildDemoResult } = await import("./demo-data.ts");
  const demo = buildDemoResult();
  assert.equal("score" in demo.verdict, false);
  assert.equal("label" in demo.verdict, false);
  assert.notEqual(demo.verdict.primaryCause, "No dominant failure signature — review the timeline.");
  assert.ok(demo.verdict.notes.length >= 1);
  const blob = JSON.stringify(demo.verdict);
  assert.equal(/"score"\s*:/.test(blob), false, blob.slice(0, 200));
  assert.equal(/"label"\s*:/.test(blob), false, blob.slice(0, 200));
});
