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
  bssid?: string;
  apName?: string;
  ssid: string;
  band: string;
  connect: number | null;
  disconnect: number | null;
  duration: number | null;
  hitByRadar?: boolean;
  radarHits?: number[];
};

export type RadioEvent = {
  timestamp: number;
  ap: string;
  apName: string;
  band: string;
  channel: number | null;
  preChannel: number | null;
  bandwidth: number | null;
  preBandwidth: number | null;
  power: number | null;
  prePower: number | null;
  event: string;
  label: string;
  usage: string;
  preUsage: string;
  channelChanged: boolean;
  highlight?: boolean;
  onClientAp?: boolean;
};

export type CollabCall = {
  app: string;
  appLabel: string;
  mac: string;
  meetingId: string;
  start: number | null;
  end: number | null;
  duration: number | null;
  audioQuality: number | null;
  videoQuality: number | null;
  screenShareQuality: number | null;
  rating: number | null;
  poor: boolean;
  teams: boolean;
};

export type RadarFact = {
  call?: string | null;
  meetingId?: string | null;
  callStart?: number | null;
  callEnd?: number | null;
  callDuration?: number | null;
  audioQuality?: number | null;
  videoQuality?: number | null;
  clientAp?: string | null;
  clientApName?: string | null;
  radarEvent?: string | null;
  radarType?: string | null;
  radarTime?: number | null;
  radarAp?: string | null;
  radarApName?: string | null;
  radarChannel?: string | null;
  radarWidth?: string | null;
  radarPower?: string | null;
  radarBand?: string | null;
  dropType?: string | null;
  dropTime?: number | null;
};

export type RadarAlert = {
  id: string;
  severity: "crit";
  title: string;
  summary: string;
  sessionAp: string;
  sessionApName: string;
  sessionConnect: number | null;
  sessionDisconnect: number | null;
  sessionDuration: number | null;
  radarEvent: string;
  radarTime: number | null;
  radarAp: string;
  radarApName: string;
  radarChannel?: string | null;
  radarWidth?: string | null;
  radarPower?: string | null;
  radarBand?: string | null;
  call?: string | null;
  meetingId?: string | null;
  callStart?: number | null;
  callEnd?: number | null;
  detail: RadarFact;
  session: ClientSession;
  radio: RadioEvent;
  radios?: RadioEvent[];
};

export type Correlation = {
  id: string;
  title: string;
  evidence: string;
  confidence: "high" | "medium" | "low";
  severity: "crit" | "warn" | "info";
  highlight?: boolean;
  detail?: RadarFact;
};

export type HealthVerdict = {
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
  radioEvents: RadioEvent[];
  radioEventsUnavailable: string | null;
  clientRadarEvents?: RadioEvent[];
  radioStoreStats?: {
    scanned: number;
    dropped: number;
    radars: number;
    kept: number;
    clientHits: number;
  };
  calls: CollabCall[];
  callsUnavailable: string | null;
  radarAlerts: RadarAlert[];
};

export type ConnectResult = {
  email: string;
  orgs: MistOrg[];
};
