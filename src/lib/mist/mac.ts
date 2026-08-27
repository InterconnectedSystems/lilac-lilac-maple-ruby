export function hexMac(raw: unknown): string {
  return String(raw ?? "")
    .replace(/[^0-9a-fA-F]/g, "")
    .toLowerCase();
}

export function normalizeMac(raw: string): string {
  const cleaned = hexMac(raw);
  if (cleaned.length !== 12) {
    throw new Error("MAC must be 12 hex digits (colons/dashes optional).");
  }
  return cleaned;
}

export function formatMac(mac: string): string {
  const n = hexMac(mac);
  if (n.length !== 12) return String(mac ?? "");
  return n.match(/.{2}/g)!.join(":");
}

export function mistDeviceId(mac: string): string {
  const h = hexMac(mac);
  return h.length === 12 ? `00000000-0000-0000-1000-${h}` : "";
}
