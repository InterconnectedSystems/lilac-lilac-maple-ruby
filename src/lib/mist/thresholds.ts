export const RSSI_GOOD = -65;
export const RSSI_WARN = -75;
export const SNR_GOOD = 25;
export const SNR_WARN = 15;

export type Band = "good" | "warn" | "crit" | "unknown";

export function rssiBand(rssi: number | null | undefined): Band {
  if (rssi === null || rssi === undefined || Number.isNaN(rssi)) return "unknown";
  if (rssi < RSSI_WARN) return "crit";
  if (rssi < RSSI_GOOD) return "warn";
  return "good";
}

export function snrBand(snr: number | null | undefined): Band {
  if (snr === null || snr === undefined || Number.isNaN(snr)) return "unknown";
  if (snr < SNR_WARN) return "crit";
  if (snr < SNR_GOOD) return "warn";
  return "good";
}

export function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
