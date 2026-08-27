/** IEEE 802.11 deauth/disassoc reason codes most useful for disconnect RCA. */
export const REASON_CODES: Record<number, string> = {
  1: "Unspecified",
  2: "Previous authentication no longer valid",
  3: "STA leaving IBSS/ESS",
  4: "Disassociated due to inactivity",
  5: "AP cannot handle all currently associated STAs",
  6: "Class 2 frame from nonauthenticated STA",
  7: "Class 3 frame from nonassociated STA",
  8: "STA leaving BSS",
  9: "STA requesting (re)association is not authenticated",
  10: "Unacceptable power capability",
  13: "Invalid information element",
  14: "MIC failure",
  15: "4-way handshake timeout",
  16: "Group key handshake timeout",
  17: "IE in 4-way handshake different from (re)assoc",
  18: "Invalid group cipher",
  19: "Invalid pairwise cipher",
  20: "Invalid AKMP",
  23: "IEEE 802.1X authentication failed",
  39: "The QoS AP lacks sufficient bandwidth",
};

export function describeReason(code: number | string | undefined): string | null {
  if (code === undefined || code === null || code === "") return null;
  const n = typeof code === "number" ? code : Number.parseInt(String(code), 10);
  if (Number.isNaN(n)) return String(code);
  return REASON_CODES[n] ? `${n} — ${REASON_CODES[n]}` : String(n);
}
