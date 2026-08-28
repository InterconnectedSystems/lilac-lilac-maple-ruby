import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { connectMist, diagnoseClient, listSites } from "./client";
import { MIST_HOSTS } from "./hosts";

const creds = z.object({
  token: z.string().min(8).max(512),
  host: z.enum(MIST_HOSTS),
});

export const mistConnect = createServerFn({ method: "POST" })
  .validator(creds)
  .handler(async ({ data }) => connectMist(data));

export const mistListSites = createServerFn({ method: "POST" })
  .validator(
    creds.extend({
      orgId: z.string().min(4).max(80),
    }),
  )
  .handler(async ({ data }) => listSites(data));

export const mistDiagnose = createServerFn({ method: "POST" })
  .validator(
    creds.extend({
      orgId: z.string().min(4).max(80),
      siteId: z.string().min(4).max(80),
      siteName: z.string().max(120),
      mac: z.string().min(12).max(32),
      duration: z.enum(["1h", "6h", "1d", "1w"]),
      live: z.boolean().optional(),
    }),
  )
  .handler(async ({ data }) => diagnoseClient(data));
