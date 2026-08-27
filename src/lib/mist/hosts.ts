export const MIST_HOSTS = [
  "api.gc2.mist.com",
  "api.mist.com",
  "api.gc1.mist.com",
  "api.ac2.mist.com",
  "api.gc4.mist.com",
  "api.eu.mist.com",
  "api.gc3.mist.com",
  "api.ac5.mist.com",
  "api.gc5.mist.com",
] as const;

export type MistHost = (typeof MIST_HOSTS)[number];

export const DEFAULT_HOST: MistHost = "api.gc2.mist.com";

export function isMistHost(value: string): value is MistHost {
  return (MIST_HOSTS as readonly string[]).includes(value);
}
