export type DurationKey = "1h" | "6h" | "1d" | "1w";

export type MistOrg = { id: string; name: string };
export type MistSite = { id: string; name: string };

export type ClientStats = {
  mac: string;
  hostname: string | null;
  manufacture: string | null;
  os: string | null;
  model: string | null;
  ssid: string | null;
  vlan: string | number | null;
  ip: string | null;
  ap: string | null;
  band: string | null;
  channel: string | number | null;
  proto: string | null;
  rssi: number | null;
  snr: number | null;
  txRate: number | null;
  rxRate: number | null;
  uptime: number | null;
  lastSeen: number | null;
  txBytes: number | null;
  rxBytes: number | null;
  username: string | null;
  keyMgmt: string | null;
  txRetries: number | null;
  rxRetries: number | null;
  dualBand: boolean | null;
};

export type ClientEvent = {
  timestamp: number;
  type: string;
  text: string;
  ap: string;
  ssid: string;
  band: string;
  channel: string | number | null;
  reason: string | number | null;
  negative: boolean;
};

export type ClientSession = {
  ap: string;
  ssid: string;
  band: string;
  connect: number | null;
  disconnect: number | null;
  duration: number | null;
};

export type Correlation = {
  id: string;
  title: string;
  evidence: string;
  confidence: "high" | "medium" | "low";
  severity: "crit" | "warn" | "info";
};

export type HealthVerdict = {
  score: number;
  label: "Healthy" | "Degraded" | "Critical";
  primaryCause: string;
  notes: string[];
  correlations: Correlation[];
};

export type RfSample = {
  t: number;
  rssi: number | null;
  snr: number | null;
  online: boolean;
};

export type OccupancyBar = {
  channel: number;
  site: number;
  external: number;
  nonWifi: number;
  serving: boolean;
};

export type RadioLive = {
  channel: number | null;
  bandwidth: number | string | null;
  power: number | null;
  numClients: number | null;
  utilAll: number;
  utilTx: number;
  utilRxInBss: number;
  utilRxOtherBss: number;
  utilNonWifi: number;
  utilUnknownWifi: number;
  utilUndecodable: number;
};

export type DominantAp = {
  apMac: string;
  apNameHint: string;
  source: string;
  dwellSeconds: number;
  dwellShare: number;
  bandHint: string;
  marvisMentioned: boolean;
  marvisAps: string[];
  marvisName: string | null;
  deviceId: string;
  selectionNote: string;
  fallback: boolean;
};

export type ApRadio = DominantAp & {
  apName: string;
  status: string;
  band: string;
  radio: RadioLive | null;
  channels: OccupancyBar[];
  scope: "ap" | "site";
  unavailable: string | null;
  lastSeen?: number | null;
};

export type DiagnoseResult = {
  demo: boolean;
  host: string;
  orgId: string;
  siteId: string;
  siteName: string;
  mac: string;
  duration: DurationKey;
  online: boolean;
  stats: ClientStats | null;
  sightings: ClientStats[];
  events: ClientEvent[];
  sessions: ClientSession[];
  marvisText: string | null;
  marvisUnavailable: boolean;
  verdict: HealthVerdict;
  fetchedAt: number;
  apRadio: ApRadio | null;
};

export type ConnectResult = {
  email: string;
  orgs: MistOrg[];
};
