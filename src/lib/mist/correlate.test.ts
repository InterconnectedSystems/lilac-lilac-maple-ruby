import assert from "node:assert/strict";
import test from "node:test";
import { buildCorrelations } from "./correlate.ts";
import { buildVerdict, pickEvent } from "./classify.ts";
import type { ClientEvent, ClientStats } from "./types.ts";

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
  assert.equal(v.label, "Critical");
  assert.ok(v.correlations.length >= 2);
});

test("SNR collapse with decent RSSI is tagged as noise, not coverage", () => {
  const cors = buildCorrelations({ ...baseStats, rssi: -62, snr: 8, txRetries: 12 }, [], []);
  assert.equal(cors[0]?.id, "rf-noise");
});

test("healthy empty window has no correlations", () => {
  const v = buildVerdict(null, [], []);
  assert.deepEqual(v.correlations, []);
  assert.equal(v.label, "Healthy");
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
