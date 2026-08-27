import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Pause,
  Radio,
  Search,
  Shield,
  ShieldCheck,
  Wifi,
  WifiOff,
} from "lucide-react";
import { mistConnect, mistDiagnose, mistListSites } from "@/lib/mist/actions";
import { buildDemoResult, DEMO_MAC } from "@/lib/mist/demo-data";
import { DEFAULT_HOST, MIST_HOSTS, type MistHost } from "@/lib/mist/hosts";
import { filterOccupancy, type UniiFilter } from "@/lib/mist/occupancy";
import { formatMac, normalizeMac } from "@/lib/mist/mac";
import { describeReason } from "@/lib/mist/reason-codes";
import { rssiBand, snrBand, type Band } from "@/lib/mist/thresholds";
import type {
  ApRadio,
  Correlation,
  DiagnoseResult,
  DurationKey,
  MistOrg,
  MistSite,
  OccupancyBar,
  RfSample,
} from "@/lib/mist/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { fmtBytes, fmtDuration, fmtTime } from "./format";

type Phase = "connect" | "scope" | "board";
type LiveSec = 3 | 15 | 30 | 60;

function bandClass(band: Band): string {
  if (band === "crit") return "text-crit";
  if (band === "warn") return "text-warn";
  if (band === "good") return "text-good";
  return "text-muted";
}

function Metric({
  label,
  value,
  hint,
  band,
}: {
  label: string;
  value: string;
  hint?: string;
  band?: Band;
}) {
  const pulse = band === "crit" ? "metric-crit" : band === "warn" ? "metric-warn" : "";
  return (
    <div
      className={cn(
        "min-w-0 rounded-xl border border-border bg-surface p-3 sm:p-4 min-h-24",
        pulse,
      )}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-subtle">{label}</p>
      <p className={cn("mt-1.5 font-mono text-xl sm:text-2xl tabular-nums font-medium break-all", bandClass(band ?? "unknown"))}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-subtle">
        {label}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full min-h-11 min-w-0 rounded-lg border border-border bg-surface-2 px-3 text-base text-fg placeholder:text-subtle focus:outline-2 focus:outline-offset-2 focus:outline-ring";

export function ConsoleApp() {
  const [phase, setPhase] = useState<Phase>("connect");
  const [host, setHost] = useState<MistHost>(DEFAULT_HOST);
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [orgs, setOrgs] = useState<MistOrg[]>([]);
  const [orgId, setOrgId] = useState("");
  const [sites, setSites] = useState<MistSite[]>([]);
  const [siteId, setSiteId] = useState("");
  const [mac, setMac] = useState("");
  const [duration, setDuration] = useState<DurationKey>("1d");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DiagnoseResult | null>(null);
  const [live, setLive] = useState(false);
  const [liveSec, setLiveSec] = useState<LiveSec>(15);
  const [samples, setSamples] = useState<RfSample[]>([]);

  const siteName = sites.find((s) => s.id === siteId)?.name ?? result?.siteName ?? "";
  const liveRef = useRef({ live, liveSec, phase, result, token, host, orgId, siteId, siteName, mac, duration, busy });
  liveRef.current = { live, liveSec, phase, result, token, host, orgId, siteId, siteName, mac, duration, busy };

  async function runDiagnose(fromLive = false) {
    const snap = liveRef.current;
    if (snap.busy && fromLive) return;
    setBusy(true);
    if (!fromLive) setError(null);
    try {
      if (snap.result?.demo) {
        const demo = buildDemoResult({ jitter: fromLive });
        setResult(demo);
        setPhase("board");
        return;
      }
      const nmac = normalizeMac(snap.mac || snap.result?.mac || "");
      const res = await mistDiagnose({
        data: {
          token: snap.token.trim(),
          host: snap.host,
          orgId: snap.orgId,
          siteId: snap.siteId,
          siteName: snap.siteName,
          mac: nmac,
          duration: snap.duration,
        },
      });
      setResult(res);
      setPhase("board");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Diagnose failed.";
      setError(msg);
      if (/429|rate limit/i.test(msg)) setLive(false);
    } finally {
      setBusy(false);
    }
  }

  async function onConnect(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await mistConnect({ data: { token: token.trim(), host } });
      setEmail(res.email);
      setOrgs(res.orgs);
      setOrgId(res.orgs[0]?.id ?? "");
      setPhase("scope");
      if (res.orgs[0]) {
        const listed = await mistListSites({
          data: { token: token.trim(), host, orgId: res.orgs[0].id },
        });
        setSites(listed);
        setSiteId(listed[0]?.id ?? "");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connect failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onOrgChange(id: string) {
    setOrgId(id);
    setBusy(true);
    setError(null);
    try {
      const listed = await mistListSites({ data: { token: token.trim(), host, orgId: id } });
      setSites(listed);
      setSiteId(listed[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not list sites.");
    } finally {
      setBusy(false);
    }
  }

  function loadDemo() {
    setError(null);
    setEmail("demo@local");
    setOrgs([{ id: "demo-org", name: "Interconnected Systems (sample)" }]);
    setOrgId("demo-org");
    setSites([{ id: "demo-site", name: "Sample HQ — Floor 2" }]);
    setSiteId("demo-site");
    setMac(formatMac(DEMO_MAC));
    const demo = buildDemoResult();
    setResult(demo);
    setSamples([]);
    setLive(false);
    setPhase("board");
  }

  useEffect(() => {
    if (!result) return;
    setSamples((prev) => {
      const next: RfSample = {
        t: result.fetchedAt,
        rssi: result.stats?.rssi ?? null,
        snr: result.stats?.snr ?? null,
        online: result.online,
      };
      const last = prev[prev.length - 1];
      if (last && last.t === next.t) return prev;
      return [...prev.slice(-47), next];
    });
  }, [result]);

  useEffect(() => {
    if (!live || phase !== "board") return;
    const id = window.setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      void runDiagnose(true);
    }, liveSec * 1000);
    return () => window.clearInterval(id);
  }, [live, liveSec, phase]);

  return (
    <div className="app-shell bg-bg text-fg">
      <header className="app-header sticky top-0 z-20 border-b border-border bg-bg/90 backdrop-blur-sm">
        <div className="mx-auto flex w-full max-w-6xl min-w-0 items-center justify-between gap-2 px-3 py-3 sm:px-4 sm:py-4">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
              <Radio className="size-4 text-accent" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-tight">Mist Disconnect Console</p>
              <p className="truncate text-xs text-muted">
                {host}
                {email ? ` · ${email}` : ""}
              </p>
            </div>
          </div>
          {phase !== "connect" ? (
            <Button
              variant="ghost"
              className="shrink-0 px-3"
              onClick={() => {
                setPhase("connect");
                setResult(null);
                setLive(false);
                setSamples([]);
              }}
            >
              <ArrowLeft className="size-4" />
              <span className="hidden sm:inline">Session</span>
            </Button>
          ) : null}
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl min-w-0 px-3 py-5 sm:px-4 sm:py-6 pb-20">
        {error ? (
          <div
            role="alert"
            className="mb-4 rounded-xl border border-crit/40 bg-surface px-4 py-3 text-sm text-crit"
          >
            {error}
          </div>
        ) : null}

        {phase === "connect" ? (
          <ConnectView
            host={host}
            token={token}
            busy={busy}
            onHost={setHost}
            onToken={setToken}
            onSubmit={onConnect}
            onDemo={loadDemo}
          />
        ) : null}

        {phase === "scope" ? (
          <ScopeView
            orgs={orgs}
            orgId={orgId}
            sites={sites}
            siteId={siteId}
            mac={mac}
            duration={duration}
            busy={busy}
            onOrg={onOrgChange}
            onSite={setSiteId}
            onMac={setMac}
            onDuration={setDuration}
            onSubmit={(e) => {
              e.preventDefault();
              void runDiagnose(false);
            }}
          />
        ) : null}

        {phase === "board" && result ? (
          <BoardView
            result={result}
            mac={mac || formatMac(result.mac)}
            duration={duration}
            busy={busy}
            live={live}
            liveSec={liveSec}
            samples={samples}
            onMac={setMac}
            onDuration={setDuration}
            onLive={setLive}
            onLiveSec={setLiveSec}
            onRerun={() => void runDiagnose(false)}
            onBack={() => {
              setLive(false);
              setPhase(result.demo ? "connect" : "scope");
            }}
          />
        ) : null}
      </main>
    </div>
  );
}

function ConnectView({
  host,
  token,
  busy,
  onHost,
  onToken,
  onSubmit,
  onDemo,
}: {
  host: MistHost;
  token: string;
  busy: boolean;
  onHost: (h: MistHost) => void;
  onToken: (t: string) => void;
  onSubmit: (e: FormEvent) => void;
  onDemo: () => void;
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
      <form
        onSubmit={onSubmit}
        className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-6"
      >
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Client disconnect RCA</h1>
        <p className="mt-2 text-sm text-muted">
          Investigate why a station drops: RF, 802.11 reason codes, DHCP after roam, and Marvis — without dumping the whole site.
        </p>
        <div className="mt-5 grid gap-4">
          <Field label="API region">
            <select
              className={inputClass}
              value={host}
              onChange={(e) => onHost(e.target.value as MistHost)}
            >
              {MIST_HOSTS.map((h) => (
                <option key={h} value={h}>
                  {h}
                  {h === DEFAULT_HOST ? " (default)" : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Read-only API token">
            <input
              className={cn(inputClass, "font-mono")}
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="Observer / read-only token"
              value={token}
              onChange={(e) => onToken(e.target.value)}
              required
              minLength={8}
              suppressHydrationWarning
            />
          </Field>
          <Button type="submit" disabled={busy} className="w-full sm:w-auto">
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Shield className="size-4" />}
            Validate token
          </Button>
          <Button type="button" variant="secondary" onClick={onDemo} className="w-full sm:w-auto">
            Run sample investigation
          </Button>
        </div>
      </form>

      <aside className="grid min-w-0 gap-4">
        <section className="rounded-2xl border border-accent/35 bg-surface p-4 sm:p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <ShieldCheck className="size-4" /> Standard practice
          </h2>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li>
              <strong className="text-fg">Use a read-only (Observer) token.</strong> This console only issues GET requests. Never paste Org Admin, Super User, or write-enabled keys.
            </li>
            <li>
              Create it under <span className="text-fg">Organization → Settings → API Tokens</span> with Observer (or equivalent read) privileges scoped to the org or site you are troubleshooting.
            </li>
            <li>
              The token stays in this browser tab, is forwarded only to the Mist region you select, and is never written to a database. Close the tab when finished. Rotate the token if it was exposed.
            </li>
            <li>
              Observer still sees client identifiers (MAC, hostname, username). Treat captures as operational data, not something to screenshot into tickets unredacted.
            </li>
          </ul>
        </section>

        <section className="rounded-2xl border border-border bg-surface p-4 sm:p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">What gets correlated</h2>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li>RSSI/SNR vs deauth reason (coverage vs idle vs handshake).</li>
            <li>DHCP/DNS failures in the 2 minutes after a roam or assoc (L3 after join).</li>
            <li>AP ping-pong, 5→2.4 band drops, short sessions, TX retries.</li>
          </ul>
        </section>
      </aside>
    </div>
  );
}

function ScopeView({
  orgs,
  orgId,
  sites,
  siteId,
  mac,
  duration,
  busy,
  onOrg,
  onSite,
  onMac,
  onDuration,
  onSubmit,
}: {
  orgs: MistOrg[];
  orgId: string;
  sites: MistSite[];
  siteId: string;
  mac: string;
  duration: DurationKey;
  busy: boolean;
  onOrg: (id: string) => void;
  onSite: (id: string) => void;
  onMac: (m: string) => void;
  onDuration: (d: DurationKey) => void;
  onSubmit: (e: FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="mx-auto w-full max-w-xl min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-6">
      <h1 className="text-xl font-semibold tracking-tight">Select site and client</h1>
      <p className="mt-1 text-sm text-muted">Token validated. Choose the site, then the MAC under investigation.</p>
      <div className="mt-5 grid gap-4">
        <Field label="Organization">
          <select className={inputClass} value={orgId} onChange={(e) => onOrg(e.target.value)}>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Site">
          <select className={inputClass} value={siteId} onChange={(e) => onSite(e.target.value)} required>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Client MAC">
          <input
            className={cn(inputClass, "font-mono")}
            placeholder="aa:bb:cc:dd:ee:ff"
            inputMode="text"
            autoCapitalize="off"
            autoCorrect="off"
            value={mac}
            onChange={(e) => onMac(e.target.value)}
            required
          />
        </Field>
        <Field label="Lookback">
          <select
            className={inputClass}
            value={duration}
            onChange={(e) => onDuration(e.target.value as DurationKey)}
          >
            <option value="1h">1 hour</option>
            <option value="6h">6 hours</option>
            <option value="1d">1 day</option>
            <option value="1w">1 week</option>
          </select>
        </Field>
        <Button type="submit" disabled={busy || !siteId} className="w-full">
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
          Diagnose
        </Button>
      </div>
    </form>
  );
}

function Sparkline({ samples, field }: { samples: RfSample[]; field: "rssi" | "snr" }) {
  const pts = samples
    .map((s, i) => ({ i, v: s[field] }))
    .filter((p): p is { i: number; v: number } => p.v != null);
  if (pts.length < 2) {
    return <p className="text-xs text-subtle">Need two live samples to plot {field.toUpperCase()}.</p>;
  }
  const w = 280;
  const h = 56;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const d = pts
    .map((p, idx) => {
      const x = (idx / (pts.length - 1)) * (w - 8) + 4;
      const y = h - 6 - ((p.v - min) / span) * (h - 12);
      return `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-14 w-full" role="img" aria-label={`${field} sparkline`}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" className="text-accent" />
    </svg>
  );
}

function BoardView({
  result,
  mac,
  duration,
  busy,
  live,
  liveSec,
  samples,
  onMac,
  onDuration,
  onLive,
  onLiveSec,
  onRerun,
  onBack,
}: {
  result: DiagnoseResult;
  mac: string;
  duration: DurationKey;
  busy: boolean;
  live: boolean;
  liveSec: LiveSec;
  samples: RfSample[];
  onMac: (m: string) => void;
  onDuration: (d: DurationKey) => void;
  onLive: (v: boolean) => void;
  onLiveSec: (s: LiveSec) => void;
  onRerun: () => void;
  onBack: () => void;
}) {
  const s = result.stats;
  const rb = rssiBand(s?.rssi);
  const sb = snrBand(s?.snr);
  const disconnects = useMemo(
    () => result.events.filter((e) => /DEAUTH|DISASSOC|DISCONNECT/i.test(e.type)).length,
    [result.events],
  );
  const verdictTone =
    result.verdict.label === "Critical"
      ? "text-crit"
      : result.verdict.label === "Degraded"
        ? "text-warn"
        : "text-good";

  return (
    <div className="grid min-w-0 gap-4 sm:gap-5">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-subtle">{result.siteName}</p>
          <h1 className="mt-1 flex min-w-0 flex-wrap items-center gap-2 font-mono text-lg sm:text-2xl">
            <span className="break-all">{formatMac(result.mac)}</span>
            {result.online ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-good">
                <Wifi className="size-3" /> seen
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted">
                <WifiOff className="size-3" /> stale
              </span>
            )}
            {live ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-accent/40 px-2 py-0.5 text-xs text-accent">
                <span className="live-dot size-1.5 rounded-full bg-accent" /> live
              </span>
            ) : null}
            {result.demo ? (
              <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">sample</span>
            ) : null}
          </h1>
          <p className="mt-1 text-xs text-subtle">
            Last poll{" "}
            {new Date(result.fetchedAt || Date.now()).toLocaleString(undefined, {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </p>
        </div>

        <form
          className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_7rem_auto_auto_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            onRerun();
          }}
        >
          <input
            className={cn(inputClass, "font-mono")}
            value={mac}
            onChange={(e) => onMac(e.target.value)}
            aria-label="Client MAC"
          />
          <select
            className={inputClass}
            value={duration}
            onChange={(e) => onDuration(e.target.value as DurationKey)}
            aria-label="Lookback"
          >
            <option value="1h">1h</option>
            <option value="6h">6h</option>
            <option value="1d">1d</option>
            <option value="1w">1w</option>
          </select>
          <Button type="submit" disabled={busy} className="w-full lg:w-auto">
            {busy ? <Loader2 className="size-4 animate-spin" /> : "Refresh"}
          </Button>
          <Button
            type="button"
            variant={live ? "secondary" : "primary"}
            className="w-full lg:w-auto"
            onClick={() => onLive(!live)}
          >
            {live ? <Pause className="size-4" /> : <Radio className="size-4" />}
            {live ? "Stop live" : "Live monitor"}
          </Button>
          <select
            className={inputClass}
            value={liveSec}
            onChange={(e) => onLiveSec(Number(e.target.value) as LiveSec)}
            aria-label="Poll interval"
            disabled={!live}
          >
            <option value={3}>every 3s</option>
            <option value={15}>every 15s</option>
            <option value={30}>every 30s</option>
            <option value={60}>every 60s</option>
          </select>
        </form>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-subtle">
            Live mode re-queries per-MAC stats/events and this AP's occupancy. Auto-pauses on Mist 429.
          </p>
          <Button type="button" variant="ghost" className="px-3" onClick={onBack}>
            Back
          </Button>
        </div>
      </div>

      <div
        className={cn(
          "min-w-0 rounded-2xl border bg-surface p-4 sm:p-5",
          result.verdict.label === "Critical" ? "border-crit/50 metric-crit" : "border-border",
        )}
      >
        <div className="flex flex-wrap items-center gap-3">
          {result.verdict.label === "Healthy" ? (
            <CheckCircle2 className="size-5 text-good" />
          ) : (
            <AlertTriangle className={cn("size-5", verdictTone)} />
          )}
          <p className={cn("text-lg font-semibold", verdictTone)}>
            {result.verdict.label} · score {result.verdict.score}
          </p>
        </div>
        <p className="mt-2 text-sm">{result.verdict.primaryCause}</p>
        <ul className="mt-3 grid gap-1 text-sm text-muted">
          {result.verdict.notes.map((n) => (
            <li key={n}>— {n}</li>
          ))}
        </ul>
      </div>

      <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">Correlated causes</h2>
        {!result.verdict.correlations.length ? (
          <p className="mt-3 text-sm text-muted">No multi-signal pattern in this window.</p>
        ) : (
          <ul className="mt-3 grid gap-3">
            {result.verdict.correlations.map((c) => (
              <CorrelationCard key={c.id} c={c} />
            ))}
          </ul>
        )}
      </section>

      <OccupancyPanel ap={result.apRadio} />

      <div className="grid min-w-0 gap-3 grid-cols-2 lg:grid-cols-4">
        <Metric
          label="RSSI"
          value={s?.rssi != null ? `${s.rssi} dBm` : "—"}
          hint="Good ≥ −65 · Crit < −75"
          band={rb}
        />
        <Metric
          label="SNR"
          value={s?.snr != null ? `${s.snr} dB` : "—"}
          hint="Good ≥ 25 · Crit < 15"
          band={sb}
        />
        <Metric
          label="Disconnects"
          value={String(disconnects)}
          hint={`Window ${result.duration}`}
          band={disconnects >= 3 ? "crit" : disconnects >= 1 ? "warn" : "good"}
        />
        <Metric
          label="TX retries"
          value={s?.txRetries != null ? String(s.txRetries) : "—"}
          hint={s?.dualBand ? "dual-band client" : "retries"}
          band={s?.txRetries != null && s.txRetries >= 80 ? (rb === "good" ? "warn" : "crit") : "unknown"}
        />
      </div>

      {live || samples.length > 1 ? (
        <section className="grid min-w-0 gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-border bg-surface p-4">
            <p className="text-xs uppercase tracking-wide text-subtle">RSSI over live polls</p>
            <Sparkline samples={samples} field="rssi" />
          </div>
          <div className="rounded-2xl border border-border bg-surface p-4">
            <p className="text-xs uppercase tracking-wide text-subtle">SNR over live polls</p>
            <Sparkline samples={samples} field="snr" />
          </div>
        </section>
      ) : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">Identity / radio</h2>
          {!s ? (
            <p className="mt-3 text-sm text-muted">No live stats for this MAC on the site.</p>
          ) : (
            <dl className="mt-3 grid grid-cols-[minmax(5.5rem,7rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
              <Row k="Hostname" v={s.hostname} />
              <Row k="User" v={s.username} />
              <Row k="Vendor" v={s.manufacture} />
              <Row k="OS / model" v={[s.os, s.model].filter(Boolean).join(" / ")} />
              <Row k="SSID" v={s.ssid} />
              <Row k="VLAN" v={s.vlan != null ? String(s.vlan) : null} />
              <Row k="IP" v={s.ip} />
              <Row k="AP" v={s.ap} />
              <Row k="Band / ch" v={[s.band, s.channel].filter((x) => x != null && x !== "").join(" / ")} />
              <Row k="Protocol" v={s.proto} />
              <Row k="Key mgmt" v={s.keyMgmt} />
              <Row k="Tx / Rx" v={[s.txRate, s.rxRate].every((x) => x == null) ? null : `${s.txRate ?? "—"} / ${s.rxRate ?? "—"}`} />
              <Row k="Retries" v={s.txRetries != null ? `${s.txRetries} tx / ${s.rxRetries ?? "—"} rx` : null} />
              <Row k="Uptime" v={fmtDuration(s.uptime)} />
              <Row k="Last seen" v={fmtTime(s.lastSeen)} />
              <Row k="Bytes" v={`${fmtBytes(s.txBytes)} / ${fmtBytes(s.rxBytes)}`} />
            </dl>
          )}
        </section>

        <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">Sessions</h2>
          {!result.sessions.length ? (
            <p className="mt-3 text-sm text-muted">No session records in this window.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {result.sessions.slice(0, 8).map((sess, i) => {
                const short = sess.duration != null && sess.duration < 60;
                return (
                  <li key={`${sess.ap}-${sess.connect}-${i}`} className="py-2.5 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate font-mono text-xs text-muted">{sess.ap || "AP —"}</span>
                      <span className={cn("shrink-0 font-mono tabular-nums", short ? "text-crit" : "text-fg")}>
                        {fmtDuration(sess.duration)}
                      </span>
                    </div>
                    <p className="text-xs text-subtle">
                      {sess.ssid} · {sess.band || "band —"} · {fmtTime(sess.connect)}
                      {sess.disconnect ? ` → ${fmtTime(sess.disconnect)}` : " (open)"}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-subtle">
          <Activity className="size-4" /> Event timeline
        </h2>
        {!result.events.length ? (
          <p className="mt-3 text-sm text-muted">No client events returned for this window.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {result.events.slice(0, 40).map((ev, i) => (
              <li
                key={`${ev.timestamp}-${ev.type}-${i}`}
                className={cn(
                  "rounded-lg border px-3 py-2",
                  ev.negative ? "border-crit/35 bg-surface-2" : "border-border",
                )}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className={cn("break-all font-mono text-xs", ev.negative ? "text-crit" : "text-good")}>
                    {ev.negative ? "FAIL" : "OK"} · {ev.type}
                  </p>
                  <p className="font-mono text-xs text-subtle tabular-nums">{fmtTime(ev.timestamp)}</p>
                </div>
                {ev.text ? <p className="mt-1 text-sm">{ev.text}</p> : null}
                <p className="mt-1 break-words text-xs text-muted">
                  AP {ev.ap || "—"} · {ev.ssid || "SSID —"} · {ev.band || "band —"}
                  {ev.channel != null && ev.channel !== "" ? ` / ch ${ev.channel}` : ""}
                  {describeReason(ev.reason ?? undefined)
                    ? ` · ${describeReason(ev.reason ?? undefined)}`
                    : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">Marvis</h2>
        {result.marvisUnavailable || !result.marvisText ? (
          <p className="mt-3 text-sm text-muted">
            Marvis Troubleshoot not available (no subscription, empty result, or API error). Events and RF
            still stand on their own.
          </p>
        ) : (
          <pre className="mt-3 max-w-full overflow-x-auto rounded-lg bg-surface-2 p-3 text-xs leading-relaxed text-fg whitespace-pre-wrap break-words">
            {result.marvisText}
          </pre>
        )}
      </section>
    </div>
  );
}

function OccupancyPanel({ ap }: { ap: ApRadio | null }) {
  const [filter, setFilter] = useState<UniiFilter>("all");
  if (!ap) {
    return (
      <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">Current radio values</h2>
        <p className="mt-3 text-sm text-muted">No serving AP occupancy yet — run a diagnose against a live token.</p>
      </section>
    );
  }
  const bars = filterOccupancy(ap.channels ?? [], filter);
  const serving = (ap.channels ?? []).find((c) => c.serving);
  const radio = ap.radio;
  const nw = serving?.nonWifi ?? radio?.utilNonWifi ?? 0;
  const ext = serving?.external ?? 0;
  const site = serving?.site ?? radio?.utilRxInBss ?? 0;
  const chips: { id: UniiFilter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "unii-1", label: "UNII-1" },
    { id: "unii-2", label: "UNII-2" },
    { id: "unii-2ext", label: "UNII-2 Ext" },
    { id: "unii-3", label: "UNII-3" },
  ];
  return (
    <section className="min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-subtle">Current radio values</h2>
          <p className="mt-1 text-sm text-muted">
            RF as seen by the AP this client spent most of the time
            {ap.marvisMentioned ? " (Marvis) on. Marvis named this AP as well." : " on."}
          </p>
          {ap.selectionNote ? <p className="mt-1 text-xs text-subtle">{ap.selectionNote}</p> : null}
          {ap.unavailable ? <p className="mt-1 text-sm text-warn">{ap.unavailable}</p> : null}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-xs",
            ap.status === "connected" ? "border-good/40 text-good" : "border-border text-muted",
          )}
        >
          {ap.status || "unknown"}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm bg-occ-ext" /> External APs
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm bg-occ-site" /> Site APs
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm bg-occ-nonwifi" /> Non-Wi-Fi
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {chips.map((c) => (
            <button
              key={c.id}
              type="button"
              className={cn(
                "min-h-9 rounded-full border px-2.5 text-xs",
                filter === c.id
                  ? "border-accent bg-surface-2 text-fg"
                  : "border-border text-muted",
              )}
              onClick={() => setFilter(c.id)}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      <OccupancyChart bars={bars} />

      <p className="mt-2 text-[11px] leading-relaxed text-subtle">
        Channel occupancy % · serving channel in bold. Histogram is this AP's 20-min RRM scan — same
        wifi / non_wifi occupancy as Site → Radio Management → Current Radio Values. Orange Site APs
        come from this site's radios on each channel; teal is other-SSID / other-RSSI wifi. Live
        radio_stat utilization is the AP table only. Bars flash when Non-Wi-Fi ≥ 30% or total ≥ 70%.
      </p>

      <div className="mt-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-3">
        <OccTile label="Non-Wi-Fi" value={nw} tone={nw >= 30 ? "crit" : "good"} />
        <OccTile label="External APs" value={ext} tone={ext >= 30 ? "warn" : "good"} />
        <OccTile label="Site / in-BSS" value={site} tone="good" />
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-xs">
          <thead className="text-subtle uppercase tracking-wide">
            <tr>
              {["AP", "MAC", "Band", "Clients", "Channel", "Width", "Power", "Util"].map((h) => (
                <th key={h} className="pb-2 pr-3 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono">
            <tr>
              <td className="py-1.5 pr-3">{ap.apName || "—"}</td>
              <td className="py-1.5 pr-3">{ap.apMac ? formatMac(ap.apMac) : "—"}</td>
              <td className="py-1.5 pr-3">{ap.band === "24" ? "2.4 GHz" : `${ap.band || "5"} GHz`}</td>
              <td className="py-1.5 pr-3">{radio?.numClients ?? "—"}</td>
              <td className="py-1.5 pr-3 font-semibold">{radio?.channel ?? serving?.channel ?? "—"}</td>
              <td className="py-1.5 pr-3">{radio?.bandwidth != null ? `${radio.bandwidth} MHz` : "—"}</td>
              <td className="py-1.5 pr-3">{radio?.power != null ? `${radio.power} dBm` : "—"}</td>
              <td className="py-1.5 pr-3">{radio ? `${radio.utilAll}%` : "—"}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function OccTile({ label, value, tone }: { label: string; value: number; tone: "crit" | "warn" | "good" }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-surface-2 px-3 py-3",
        tone === "crit" ? "metric-crit" : tone === "warn" ? "metric-warn" : "",
      )}
    >
      <p className="text-[11px] uppercase tracking-wide text-subtle">{label}</p>
      <p
        className={cn(
          "mt-1 font-mono text-2xl tabular-nums",
          tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-good",
        )}
      >
        {value}%
      </p>
    </div>
  );
}

function OccupancyChart({ bars }: { bars: OccupancyBar[] }) {
  if (!bars.length) {
    return (
      <p className="mt-3 text-sm text-muted">
        No occupancy histogram for this AP (RRM considerations empty). Serving-channel util still shown when
        radio_stat is present.
      </p>
    );
  }
  const w = Math.max(560, bars.length * 44 + 48);
  const h = 220;
  const padL = 36;
  const padB = 28;
  const padT = 12;
  const innerH = h - padT - padB;
  const innerW = w - padL - 12;
  const gap = 6;
  const bw = Math.max(10, innerW / bars.length - gap);
  const ticks = [0, 25, 50, 75, 100];
  return (
    <div className="mt-3 overflow-x-auto">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label="Channel occupancy"
        className="h-[220px] w-full min-w-[560px]"
      >
        <text x="4" y={padT + 8} fill="currentColor" className="fill-subtle" fontSize="10">
          %
        </text>
        {ticks.map((t) => {
          const y = padT + innerH - (t / 100) * innerH;
          return (
            <g key={t}>
              <line x1={padL} x2={w - 8} y1={y} y2={y} stroke="currentColor" className="stroke-border" strokeWidth="1" />
              <text x={padL - 6} y={y + 3} textAnchor="end" fill="currentColor" className="fill-subtle" fontSize="10">
                {t}
              </text>
            </g>
          );
        })}
        {bars.map((c, i) => {
          const x = padL + i * (bw + gap) + gap / 2;
          const hN = (Math.min(100, c.nonWifi) / 100) * innerH;
          const hS = (Math.min(100, c.site) / 100) * innerH;
          const hE = (Math.min(100, c.external) / 100) * innerH;
          const tot = c.nonWifi + c.site + c.external;
          const flash = c.nonWifi >= 30 ? "occ-flash-crit" : tot >= 70 ? "occ-flash-warn" : "";
          const base = padT + innerH;
          return (
            <g key={c.channel} className={flash}>
              <rect x={x} y={base - hN} width={bw} height={hN} className="fill-occ-nonwifi" rx="2" />
              <rect x={x} y={base - hN - hS} width={bw} height={hS} className="fill-occ-site" rx="2" />
              <rect x={x} y={base - hN - hS - hE} width={bw} height={hE} className="fill-occ-ext" rx="2" />
              <text
                x={x + bw / 2}
                y={h - 8}
                textAnchor="middle"
                fill="currentColor"
                className={c.serving ? "fill-fg" : "fill-subtle"}
                fontSize={c.serving ? 12 : 10}
                fontWeight={c.serving ? 700 : 400}
              >
                {c.channel}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function CorrelationCard({ c }: { c: Correlation }) {
  const tone =
    c.severity === "crit" ? "border-crit/40" : c.severity === "warn" ? "border-warn/40" : "border-border";
  const badge =
    c.severity === "crit" ? "text-crit" : c.severity === "warn" ? "text-warn" : "text-muted";
  return (
    <li className={cn("rounded-xl border bg-surface-2 px-3 py-3 sm:px-4", tone)}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className={cn("text-sm font-medium", badge)}>{c.title}</p>
        <p className="text-[11px] uppercase tracking-wide text-subtle">
          {c.confidence} · {c.severity}
        </p>
      </div>
      <p className="mt-1.5 text-sm text-muted">{c.evidence}</p>
    </li>
  );
}

function Row({ k, v }: { k: string; v: string | null | undefined }) {
  return (
    <>
      <dt className="text-subtle">{k}</dt>
      <dd className="min-w-0 break-all font-mono text-xs sm:text-sm">{v || "—"}</dd>
    </>
  );
}
