import assert from "node:assert/strict";
import test from "node:test";
import { parseMarvisApHints, pickDominantAp, matchInventory } from "./ap-select.ts";
import {
  channelsFromRrm,
  occPct,
  radioPct,
  rrmOccupancyStack,
  rrmRowsFrom,
  siteAirtimeByChannel,
  rfOccupancyCorrelations,
} from "./occupancy.ts";
import type { ApRadio, OccupancyBar } from "./types.ts";

test("radio_stat 1 is 1%, RRM 1.0 is 100%", () => {
  assert.equal(radioPct(1), 1);
  assert.equal(radioPct(13), 13);
  assert.equal(occPct(0.16), 16);
  assert.equal(occPct(1), 100);
  assert.equal(occPct(0.75), 75);
});

test("RRM stack: site vs external vs non-wifi", () => {
  assert.deepEqual(rrmOccupancyStack({ wifi: 0.16, non_wifi: 0.7, rssi: -50, channel: 153 }), [16, 0, 70]);
  assert.deepEqual(rrmOccupancyStack({ wifi: 0.05, non_wifi: 0.75, other_rssi: -62, channel: 161 }), [0, 5, 75]);
  assert.deepEqual(rrmOccupancyStack({ wifi: 0.09, non_wifi: 0, rssi: -48, channel: 144 }), [9, 0, 0]);
  assert.deepEqual(
    rrmOccupancyStack({ non_wifi: 0.75, util_score_other: 0.05, other_ssid: "ext" }),
    [0, 5, 75],
  );
  assert.deepEqual(rrmOccupancyStack({ util_score_other: 0.4, rssi: -52 }), [40, 0, 0]);
  assert.deepEqual(rrmOccupancyStack({ util_score_other: 0.4 }, true), [40, 0, 0]);
  assert.deepEqual(rrmOccupancyStack({ util_score_other: 0.05 }), [0, 5, 0]);
});

test("rrm_rows_from keyed by channel", () => {
  const keyed = rrmRowsFrom({
    100: { wifi: 0.4, rssi: -50 },
    153: { non_wifi: 0.7, wifi: 0.16, rssi: -55 },
  });
  assert.deepEqual(new Set(keyed.map((r) => Number(r.channel))), new Set([100, 153]));
});

test("inventory Site AP airtime fills orange bars; unknown wifi is teal", () => {
  const inv = [
    {
      mac: "a8f7d9f096f0",
      type: "ap",
      radio_stat: {
        band_5: {
          channel: 144,
          power: 8,
          num_clients: 0,
          util_all: 13,
          util_tx: 1,
          util_rx_in_bss: 8,
          util_rx_other_bss: 0,
          util_non_wifi: 0,
        },
      },
    },
    {
      mac: "a8f7d9f06dce",
      type: "ap",
      radio_stat: {
        band_5: {
          channel: 157,
          power: 8,
          num_clients: 0,
          util_all: 25,
          util_tx: 4,
          util_rx_in_bss: 16,
          util_rx_other_bss: 3,
          util_non_wifi: 0,
        },
      },
    },
    {
      mac: "a8f7d9f06fae",
      type: "ap",
      radio_stat: {
        band_5: {
          channel: 108,
          power: 8,
          num_clients: 2,
          util_all: 50,
          util_tx: 10,
          util_rx_in_bss: 37,
          util_rx_other_bss: 2,
          util_non_wifi: 1,
        },
      },
    },
  ];
  const air = siteAirtimeByChannel(inv, "5");
  assert.equal(air[144], 9);
  assert.equal(air[157], 20);
  assert.equal(air[108], 47);
  const rrmOnlyDirty = [
    { channel: 153, non_wifi: 0.7, util_score_other: 0.16, rssi: -52 },
    { channel: 161, non_wifi: 0.75, util_score_other: 0.05, other_ssid: "x" },
    { channel: 165, non_wifi: 1.0, other_ssid: "x" },
  ];
  const merged = channelsFromRrm(rrmOnlyDirty, 144, null, "5", air);
  const by: Record<number, OccupancyBar> = {};
  for (const c of merged) by[c.channel] = c;
  assert.equal(by[108].site, 47);
  assert.equal(by[108].external, 0);
  assert.equal(by[144].site, 9);
  assert.equal(by[144].serving, true);
  assert.equal(by[157].site, 20);
  assert.equal(by[153].nonWifi, 70);
  assert.ok(by[153].site >= 16);
  assert.equal(by[161].nonWifi, 75);
  assert.equal(by[161].external, 5);
  assert.equal(by[161].site, 0);
  assert.equal(by[165].nonWifi, 100);
});

test("adjacent-channel non-wifi correlation uses occupancy serving bar", () => {
  const apRadio: ApRadio = {
    apMac: "a8f7d9f096f0",
    apName: "MISS688-AP-F1-f0:96:f0",
    apNameHint: "MISS688-AP-F1-f0:96:f0",
    source: "marvis",
    dwellSeconds: 100,
    dwellShare: 1,
    bandHint: "5",
    marvisMentioned: true,
    marvisAps: [],
    marvisName: "MISS688-AP-F1-f0:96:f0",
    deviceId: "x",
    selectionNote: "Marvis",
    fallback: false,
    status: "connected",
    band: "5",
    radio: {
      channel: 144,
      bandwidth: 20,
      power: 8,
      numClients: 0,
      utilAll: 13,
      utilTx: 1,
      utilRxInBss: 8,
      utilRxOtherBss: 0,
      utilNonWifi: 0,
      utilUnknownWifi: 0,
      utilUndecodable: 0,
    },
    channels: [
      { channel: 144, site: 9, external: 0, nonWifi: 0, serving: true },
      { channel: 153, site: 16, external: 0, nonWifi: 76, serving: false },
    ],
    scope: "ap",
    unavailable: null,
  };
  const rf = rfOccupancyCorrelations(apRadio, null);
  assert.ok(rf.some((c) => c.id === "ap-adj-nonwifi"), rf.map((c) => c.id).join(","));
  assert.ok(!rf.some((c) => c.id === "ap-nonwifi"));
});

test("Marvis 'connected to NAME most of the time' matches inventory suffix", () => {
  const marvis = {
    results: [
      {
        category: "Device Health",
        text: " The AP is currently online. Client serv_tsc_wifi was connected to MISS688-AP-F1-f0:96:f0 most of the time.",
      },
    ],
  };
  const hints = parseMarvisApHints(marvis);
  assert.equal(hints.mostName, "MISS688-AP-F1-f0:96:f0");
  const inv = [{ mac: "a8f7d9f096f0", name: "MISS688-AP-F1-f0:96:f0", type: "ap" }];
  const hit = matchInventory(inv, { name: hints.mostName ?? "", text: hints.blob });
  assert.equal(hexOf(hit?.mac), "a8f7d9f096f0");
  const picked = pickDominantAp([], null, [], marvis, inv);
  assert.equal(picked.source, "marvis");
  assert.equal(picked.apMac, "a8f7d9f096f0");
});

function hexOf(v: unknown): string {
  return String(v ?? "").replace(/[^0-9a-fA-F]/g, "").toLowerCase();
}
