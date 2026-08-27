import { i as __toESM } from "../_runtime.mjs";
import { n as require_react } from "../_libs/@radix-ui/react-compose-refs+[...].mjs";
import { v as require_jsx_runtime } from "../_libs/@tanstack/react-router+[...].mjs";
import { n as TSS_SERVER_FUNCTION, r as getServerFnById, t as createServerFn } from "./ssr.mjs";
import { a as formatMac, d as rssiBand, f as snrBand, i as describeReason, n as MIST_HOSTS, r as buildVerdict, s as normalizeMac, t as DEFAULT_HOST } from "./mac-7PhnM4gV.mjs";
import { a as string, i as object, t as _enum } from "../_libs/zod.mjs";
import { a as ShieldCheck, c as Pause, d as ArrowLeft, f as Activity, i as Shield, l as LoaderCircle, n as WifiOff, o as Search, r as TriangleAlert, s as Radio, t as Wifi, u as CircleCheck } from "../_libs/lucide-react.mjs";
import { t as Slot } from "../_libs/radix-ui__react-slot.mjs";
import { n as clsx, t as cva } from "../_libs/class-variance-authority+clsx.mjs";
import { t as twMerge } from "../_libs/tailwind-merge.mjs";
//#region node_modules/.nitro/vite/services/ssr/assets/routes-BjXjWXNv.js
var import_react = /* @__PURE__ */ __toESM(require_react());
var import_jsx_runtime = require_jsx_runtime();
var createSsrRpc = (functionId) => {
	const url = "/_serverFn/" + functionId;
	const serverFnMeta = { id: functionId };
	const fn = async (...args) => {
		return (await getServerFnById(functionId, { origin: "server" }))(...args);
	};
	return Object.assign(fn, {
		url,
		serverFnMeta,
		[TSS_SERVER_FUNCTION]: true
	});
};
var creds = object({
	token: string().min(8).max(512),
	host: _enum(MIST_HOSTS)
});
var mistConnect = createServerFn({ method: "POST" }).validator(creds).handler(createSsrRpc("7725acdc32a8050a231a8a2a336509d2da6812591dae88b605fc06c4c61f5a5d"));
var mistListSites = createServerFn({ method: "POST" }).validator(creds.extend({ orgId: string().min(4).max(80) })).handler(createSsrRpc("41a8a3b62e44385ad046bffbed933123de76d1638e4aee370e40e6a518247b8d"));
var mistDiagnose = createServerFn({ method: "POST" }).validator(creds.extend({
	orgId: string().min(4).max(80),
	siteId: string().min(4).max(80),
	siteName: string().max(120),
	mac: string().min(12).max(32),
	duration: _enum([
		"1h",
		"6h",
		"1d",
		"1w"
	])
})).handler(createSsrRpc("f14837cc7d50bd2bc49c6433a5b7809c549e88bbb483ffc035eaba246ed4c847"));
var now = () => Math.floor(Date.now() / 1e3);
var DEMO_MAC = "0a0027c1e001";
function buildDemoResult(opts) {
	const t = now();
	const jitter = opts?.jitter ? Math.round((Math.random() - .5) * 6) : 0;
	const stats = {
		mac: DEMO_MAC,
		hostname: "DEMO-MBP",
		manufacture: "Apple",
		os: "macOS 15.5",
		model: "MacBookPro18,3",
		ssid: "CORP-WIFI",
		vlan: 40,
		ip: "10.40.12.88",
		ap: "0a0027aa1102",
		band: "5",
		channel: 149,
		proto: "ax",
		rssi: -81 + jitter,
		snr: Math.max(6, 11 + Math.round(jitter / 2)),
		txRate: 58,
		rxRate: 48,
		uptime: 214,
		lastSeen: t - 12,
		txBytes: 1843200,
		rxBytes: 9216e3,
		username: "demo.user",
		keyMgmt: "WPA2-PSK",
		txRetries: 214,
		rxRetries: 88,
		dualBand: true
	};
	const events = [
		{
			timestamp: t - 40,
			type: "CLIENT_DNS_OK",
			text: "Status code 0 Successful",
			ap: "0a0027aa1102",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 149,
			reason: null,
			negative: false
		},
		{
			timestamp: t - 90,
			type: "CLIENT_DHCP_TIMED_OUT",
			text: "DORA incomplete — no ACK",
			ap: "0a0027aa1102",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 149,
			reason: null,
			negative: true
		},
		{
			timestamp: t - 140,
			type: "CLIENT_ASSOCIATION",
			text: "Associated",
			ap: "0a0027aa1102",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 149,
			reason: null,
			negative: false
		},
		{
			timestamp: t - 148,
			type: "CLIENT_DEAUTHENTICATION",
			text: "Deauthenticated by AP",
			ap: "0a0027aa1103",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 36,
			reason: 4,
			negative: true
		},
		{
			timestamp: t - 420,
			type: "CLIENT_DEAUTHENTICATION",
			text: "4-way handshake timeout",
			ap: "0a0027aa1103",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 36,
			reason: 15,
			negative: true
		},
		{
			timestamp: t - 900,
			type: "CLIENT_ROAMED",
			text: "Roamed from 0a0027aa1103",
			ap: "0a0027aa1102",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 149,
			reason: null,
			negative: false
		},
		{
			timestamp: t - 1800,
			type: "CLIENT_AUTHORIZATION",
			text: "Authorized",
			ap: "0a0027aa1103",
			ssid: "CORP-WIFI",
			band: "5",
			channel: 36,
			reason: null,
			negative: false
		},
		{
			timestamp: t - 3600,
			type: "CLIENT_DISASSOCIATION",
			text: "STA leaving BSS",
			ap: "0a0027aa1103",
			ssid: "CORP-WIFI",
			band: "2.4",
			channel: 11,
			reason: 8,
			negative: true
		}
	];
	const sessions = [
		{
			ap: "0a0027aa1102",
			ssid: "CORP-WIFI",
			band: "5",
			connect: t - 214,
			disconnect: null,
			duration: 214
		},
		{
			ap: "0a0027aa1103",
			ssid: "CORP-WIFI",
			band: "5",
			connect: t - 480,
			disconnect: t - 148,
			duration: 28
		},
		{
			ap: "0a0027aa1103",
			ssid: "CORP-WIFI",
			band: "5",
			connect: t - 900,
			disconnect: t - 840,
			duration: 44
		},
		{
			ap: "0a0027aa1102",
			ssid: "CORP-WIFI",
			band: "5",
			connect: t - 7200,
			disconnect: t - 3600,
			duration: 3580
		}
	];
	return {
		demo: true,
		host: "api.gc2.mist.com",
		orgId: "demo-org",
		siteId: "demo-site",
		siteName: "Sample HQ — Floor 2",
		mac: DEMO_MAC,
		duration: "1d",
		online: true,
		stats,
		sightings: [stats],
		events,
		sessions,
		marvisText: JSON.stringify({
			category: "Wireless connectivity",
			reason: "Weak RSSI and handshake timeouts on AP 0a0027aa1103",
			description: "Client repeatedly deauthenticates (reason 4 inactivity, reason 15 4-way timeout) then reassociates on a farther AP with RSSI −81 dBm and SNR 11 dB.",
			recommendation: "Check AP 0a0027aa1103 radio / channel 36, verify PSK, and add coverage toward the client’s last location. DHCP timeouts after rejoin suggest the client is also struggling L3 on the new AP."
		}, null, 2),
		marvisUnavailable: false,
		verdict: buildVerdict(stats, events, sessions),
		fetchedAt: Date.now()
	};
}
function cn(...inputs) {
	return twMerge(clsx(inputs));
}
var buttonVariants = cva("inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-opacity duration-150 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring min-h-11 px-4", {
	variants: { variant: {
		primary: "bg-accent text-accent-fg hover:opacity-90",
		secondary: "bg-surface-2 text-fg border border-border hover:bg-surface-3",
		ghost: "text-muted hover:text-fg hover:bg-surface-2",
		danger: "bg-crit text-fg-on-crit hover:opacity-90"
	} },
	defaultVariants: { variant: "primary" }
});
function Button({ className, variant, asChild, ...props }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(asChild ? Slot : "button", {
		className: cn(buttonVariants({ variant }), className),
		...props
	});
}
function fmtTime(ts) {
	if (!ts) return "—";
	const ms = ts > 0xe8d4a51000 ? ts : ts * 1e3;
	try {
		return new Date(ms).toLocaleString(void 0, {
			month: "short",
			day: "numeric",
			hour: "2-digit",
			minute: "2-digit",
			second: "2-digit"
		});
	} catch {
		return String(ts);
	}
}
function fmtDuration(sec) {
	if (sec == null) return "—";
	if (sec < 60) return `${Math.round(sec)}s`;
	if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
	return `${Math.floor(sec / 3600)}h ${Math.floor(sec % 3600 / 60)}m`;
}
function fmtBytes(n) {
	if (n == null) return "—";
	if (n < 1024) return `${n} B`;
	if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
	if (n < 1073741824) return `${(n / 1024 / 1024).toFixed(1)} MB`;
	return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
function bandClass(band) {
	if (band === "crit") return "text-crit";
	if (band === "warn") return "text-warn";
	if (band === "good") return "text-good";
	return "text-muted";
}
function Metric({ label, value, hint, band }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: cn("min-w-0 rounded-xl border border-border bg-surface p-3 sm:p-4 min-h-24", band === "crit" ? "metric-crit" : band === "warn" ? "metric-warn" : ""),
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "text-xs font-medium uppercase tracking-wide text-subtle",
				children: label
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: cn("mt-1.5 font-mono text-xl sm:text-2xl tabular-nums font-medium break-all", bandClass(band ?? "unknown")),
				children: value
			}),
			hint ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "mt-1 text-xs text-muted",
				children: hint
			}) : null
		]
	});
}
function Field({ label, children }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
		className: "block min-w-0",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
			className: "mb-1.5 block text-xs font-medium uppercase tracking-wide text-subtle",
			children: label
		}), children]
	});
}
var inputClass = "w-full min-h-11 min-w-0 rounded-lg border border-border bg-surface-2 px-3 text-base text-fg placeholder:text-subtle focus:outline-2 focus:outline-offset-2 focus:outline-ring";
function ConsoleApp() {
	const [phase, setPhase] = (0, import_react.useState)("connect");
	const [host, setHost] = (0, import_react.useState)(DEFAULT_HOST);
	const [token, setToken] = (0, import_react.useState)("");
	const [email, setEmail] = (0, import_react.useState)("");
	const [orgs, setOrgs] = (0, import_react.useState)([]);
	const [orgId, setOrgId] = (0, import_react.useState)("");
	const [sites, setSites] = (0, import_react.useState)([]);
	const [siteId, setSiteId] = (0, import_react.useState)("");
	const [mac, setMac] = (0, import_react.useState)("");
	const [duration, setDuration] = (0, import_react.useState)("1d");
	const [busy, setBusy] = (0, import_react.useState)(false);
	const [error, setError] = (0, import_react.useState)(null);
	const [result, setResult] = (0, import_react.useState)(null);
	const [live, setLive] = (0, import_react.useState)(false);
	const [liveSec, setLiveSec] = (0, import_react.useState)(15);
	const [samples, setSamples] = (0, import_react.useState)([]);
	const siteName = sites.find((s) => s.id === siteId)?.name ?? result?.siteName ?? "";
	const liveRef = (0, import_react.useRef)({
		live,
		liveSec,
		phase,
		result,
		token,
		host,
		orgId,
		siteId,
		siteName,
		mac,
		duration,
		busy
	});
	liveRef.current = {
		live,
		liveSec,
		phase,
		result,
		token,
		host,
		orgId,
		siteId,
		siteName,
		mac,
		duration,
		busy
	};
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
			const res = await mistDiagnose({ data: {
				token: snap.token.trim(),
				host: snap.host,
				orgId: snap.orgId,
				siteId: snap.siteId,
				siteName: snap.siteName,
				mac: nmac,
				duration: snap.duration
			} });
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
	async function onConnect(e) {
		e.preventDefault();
		setBusy(true);
		setError(null);
		try {
			const res = await mistConnect({ data: {
				token: token.trim(),
				host
			} });
			setEmail(res.email);
			setOrgs(res.orgs);
			setOrgId(res.orgs[0]?.id ?? "");
			setPhase("scope");
			if (res.orgs[0]) {
				const listed = await mistListSites({ data: {
					token: token.trim(),
					host,
					orgId: res.orgs[0].id
				} });
				setSites(listed);
				setSiteId(listed[0]?.id ?? "");
			}
		} catch (err) {
			setError(err instanceof Error ? err.message : "Connect failed.");
		} finally {
			setBusy(false);
		}
	}
	async function onOrgChange(id) {
		setOrgId(id);
		setBusy(true);
		setError(null);
		try {
			const listed = await mistListSites({ data: {
				token: token.trim(),
				host,
				orgId: id
			} });
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
		setOrgs([{
			id: "demo-org",
			name: "Interconnected Systems (sample)"
		}]);
		setOrgId("demo-org");
		setSites([{
			id: "demo-site",
			name: "Sample HQ — Floor 2"
		}]);
		setSiteId("demo-site");
		setMac(formatMac(DEMO_MAC));
		const demo = buildDemoResult();
		setResult(demo);
		setSamples([]);
		setLive(false);
		setPhase("board");
	}
	(0, import_react.useEffect)(() => {
		if (!result) return;
		setSamples((prev) => {
			const next = {
				t: result.fetchedAt,
				rssi: result.stats?.rssi ?? null,
				snr: result.stats?.snr ?? null,
				online: result.online
			};
			const last = prev[prev.length - 1];
			if (last && last.t === next.t) return prev;
			return [...prev.slice(-47), next];
		});
	}, [result]);
	(0, import_react.useEffect)(() => {
		if (!live || phase !== "board") return;
		const id = window.setInterval(() => {
			if (typeof document !== "undefined" && document.hidden) return;
			runDiagnose(true);
		}, liveSec * 1e3);
		return () => window.clearInterval(id);
	}, [
		live,
		liveSec,
		phase
	]);
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "app-shell bg-bg text-fg",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("header", {
			className: "app-header sticky top-0 z-20 border-b border-border bg-bg/90 backdrop-blur-sm",
			children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "mx-auto flex w-full max-w-6xl min-w-0 items-center justify-between gap-2 px-3 py-3 sm:px-4 sm:py-4",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "flex min-w-0 items-center gap-2 sm:gap-3",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
						className: "flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Radio, { className: "size-4 text-accent" })
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "min-w-0",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "truncate text-sm font-semibold tracking-tight",
							children: "Mist Disconnect Console"
						}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
							className: "truncate text-xs text-muted",
							children: [host, email ? ` · ${email}` : ""]
						})]
					})]
				}), phase !== "connect" ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(Button, {
					variant: "ghost",
					className: "shrink-0 px-3",
					onClick: () => {
						setPhase("connect");
						setResult(null);
						setLive(false);
						setSamples([]);
					},
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(ArrowLeft, { className: "size-4" }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
						className: "hidden sm:inline",
						children: "Session"
					})]
				}) : null]
			})
		}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("main", {
			className: "mx-auto w-full max-w-6xl min-w-0 px-3 py-5 sm:px-4 sm:py-6 pb-20",
			children: [
				error ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
					role: "alert",
					className: "mb-4 rounded-xl border border-crit/40 bg-surface px-4 py-3 text-sm text-crit",
					children: error
				}) : null,
				phase === "connect" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ConnectView, {
					host,
					token,
					busy,
					onHost: setHost,
					onToken: setToken,
					onSubmit: onConnect,
					onDemo: loadDemo
				}) : null,
				phase === "scope" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ScopeView, {
					orgs,
					orgId,
					sites,
					siteId,
					mac,
					duration,
					busy,
					onOrg: onOrgChange,
					onSite: setSiteId,
					onMac: setMac,
					onDuration: setDuration,
					onSubmit: (e) => {
						e.preventDefault();
						runDiagnose(false);
					}
				}) : null,
				phase === "board" && result ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(BoardView, {
					result,
					mac: mac || formatMac(result.mac),
					duration,
					busy,
					live,
					liveSec,
					samples,
					onMac: setMac,
					onDuration: setDuration,
					onLive: setLive,
					onLiveSec: setLiveSec,
					onRerun: () => void runDiagnose(false),
					onBack: () => {
						setLive(false);
						setPhase(result.demo ? "connect" : "scope");
					}
				}) : null
			]
		})]
	});
}
function ConnectView({ host, token, busy, onHost, onToken, onSubmit, onDemo }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "grid gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
			onSubmit,
			className: "min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-6",
			children: [
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h1", {
					className: "text-xl font-semibold tracking-tight sm:text-2xl",
					children: "Client disconnect RCA"
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "mt-2 text-sm text-muted",
					children: "Investigate why a station drops: RF, 802.11 reason codes, DHCP after roam, and Marvis — without dumping the whole site."
				}),
				/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "mt-5 grid gap-4",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Field, {
							label: "API region",
							children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("select", {
								className: inputClass,
								value: host,
								onChange: (e) => onHost(e.target.value),
								children: MIST_HOSTS.map((h) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("option", {
									value: h,
									children: [h, h === "api.gc2.mist.com" ? " (default)" : ""]
								}, h))
							})
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Field, {
							label: "Read-only API token",
							children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								className: cn(inputClass, "font-mono"),
								type: "password",
								autoComplete: "off",
								spellCheck: false,
								placeholder: "Observer / read-only token",
								value: token,
								onChange: (e) => onToken(e.target.value),
								required: true,
								minLength: 8
							})
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)(Button, {
							type: "submit",
							disabled: busy,
							className: "w-full sm:w-auto",
							children: [busy ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(LoaderCircle, { className: "size-4 animate-spin" }) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Shield, { className: "size-4" }), "Validate token"]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Button, {
							type: "button",
							variant: "secondary",
							onClick: onDemo,
							className: "w-full sm:w-auto",
							children: "Run sample investigation"
						})
					]
				})
			]
		}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("aside", {
			className: "grid min-w-0 gap-4",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "rounded-2xl border border-accent/35 bg-surface p-4 sm:p-5",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("h2", {
					className: "flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(ShieldCheck, { className: "size-4" }), " Standard practice"]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("ul", {
					className: "mt-3 space-y-2 text-sm text-muted",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("strong", {
							className: "text-fg",
							children: "Use a read-only (Observer) token."
						}), " This console only issues GET requests. Never paste Org Admin, Super User, or write-enabled keys."] }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [
							"Create it under ",
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
								className: "text-fg",
								children: "Organization → Settings → API Tokens"
							}),
							" with Observer (or equivalent read) privileges scoped to the org or site you are troubleshooting."
						] }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: "The token stays in this browser tab, is forwarded only to the Mist region you select, and is never written to a database. Close the tab when finished. Rotate the token if it was exposed." }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: "Observer still sees client identifiers (MAC, hostname, username). Treat captures as operational data, not something to screenshot into tickets unredacted." })
					]
				})]
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "rounded-2xl border border-border bg-surface p-4 sm:p-5",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
					className: "text-sm font-semibold uppercase tracking-wide text-subtle",
					children: "What gets correlated"
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("ul", {
					className: "mt-3 space-y-2 text-sm text-muted",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: "RSSI/SNR vs deauth reason (coverage vs idle vs handshake)." }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: "DHCP/DNS failures in the 2 minutes after a roam or assoc (L3 after join)." }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("li", { children: "AP ping-pong, 5→2.4 band drops, short sessions, TX retries." })
					]
				})]
			})]
		})]
	});
}
function ScopeView({ orgs, orgId, sites, siteId, mac, duration, busy, onOrg, onSite, onMac, onDuration, onSubmit }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
		onSubmit,
		className: "mx-auto w-full max-w-xl min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-6",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h1", {
				className: "text-xl font-semibold tracking-tight",
				children: "Select site and client"
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "mt-1 text-sm text-muted",
				children: "Token validated. Choose the site, then the MAC under investigation."
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "mt-5 grid gap-4",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Field, {
						label: "Organization",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("select", {
							className: inputClass,
							value: orgId,
							onChange: (e) => onOrg(e.target.value),
							children: orgs.map((o) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
								value: o.id,
								children: o.name
							}, o.id))
						})
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Field, {
						label: "Site",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("select", {
							className: inputClass,
							value: siteId,
							onChange: (e) => onSite(e.target.value),
							required: true,
							children: sites.map((s) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
								value: s.id,
								children: s.name
							}, s.id))
						})
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Field, {
						label: "Client MAC",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
							className: cn(inputClass, "font-mono"),
							placeholder: "aa:bb:cc:dd:ee:ff",
							inputMode: "text",
							autoCapitalize: "off",
							autoCorrect: "off",
							value: mac,
							onChange: (e) => onMac(e.target.value),
							required: true
						})
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Field, {
						label: "Lookback",
						children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
							className: inputClass,
							value: duration,
							onChange: (e) => onDuration(e.target.value),
							children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: "1h",
									children: "1 hour"
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: "6h",
									children: "6 hours"
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: "1d",
									children: "1 day"
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: "1w",
									children: "1 week"
								})
							]
						})
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)(Button, {
						type: "submit",
						disabled: busy || !siteId,
						className: "w-full",
						children: [busy ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(LoaderCircle, { className: "size-4 animate-spin" }) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Search, { className: "size-4" }), "Diagnose"]
					})
				]
			})
		]
	});
}
function Sparkline({ samples, field }) {
	const pts = samples.map((s, i) => ({
		i,
		v: s[field]
	})).filter((p) => p.v != null);
	if (pts.length < 2) return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
		className: "text-xs text-subtle",
		children: [
			"Need two live samples to plot ",
			field.toUpperCase(),
			"."
		]
	});
	const w = 280;
	const h = 56;
	const min = Math.min(...pts.map((p) => p.v));
	const span = Math.max(...pts.map((p) => p.v)) - min || 1;
	const d = pts.map((p, idx) => {
		const x = idx / (pts.length - 1) * 272 + 4;
		const y = 50 - (p.v - min) / span * 44;
		return `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
	}).join(" ");
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("svg", {
		viewBox: `0 0 ${w} ${h}`,
		className: "h-14 w-full",
		role: "img",
		"aria-label": `${field} sparkline`,
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("path", {
			d,
			fill: "none",
			stroke: "currentColor",
			strokeWidth: "2",
			className: "text-accent"
		})
	});
}
function BoardView({ result, mac, duration, busy, live, liveSec, samples, onMac, onDuration, onLive, onLiveSec, onRerun, onBack }) {
	const s = result.stats;
	const rb = rssiBand(s?.rssi);
	const sb = snrBand(s?.snr);
	const disconnects = (0, import_react.useMemo)(() => result.events.filter((e) => /DEAUTH|DISASSOC|DISCONNECT/i.test(e.type)).length, [result.events]);
	const verdictTone = result.verdict.label === "Critical" ? "text-crit" : result.verdict.label === "Degraded" ? "text-warn" : "text-good";
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "grid min-w-0 gap-4 sm:gap-5",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "flex min-w-0 flex-col gap-3",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "min-w-0",
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
								className: "text-xs uppercase tracking-wide text-subtle",
								children: result.siteName
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("h1", {
								className: "mt-1 flex min-w-0 flex-wrap items-center gap-2 font-mono text-lg sm:text-2xl",
								children: [
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
										className: "break-all",
										children: formatMac(result.mac)
									}),
									result.online ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
										className: "inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-good",
										children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Wifi, { className: "size-3" }), " seen"]
									}) : /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
										className: "inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted",
										children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(WifiOff, { className: "size-3" }), " stale"]
									}),
									live ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
										className: "inline-flex items-center gap-1 rounded-full border border-accent/40 px-2 py-0.5 text-xs text-accent",
										children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: "live-dot size-1.5 rounded-full bg-accent" }), " live"]
									}) : null,
									result.demo ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
										className: "rounded-full border border-border px-2 py-0.5 text-xs text-muted",
										children: "sample"
									}) : null
								]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
								className: "mt-1 text-xs text-subtle",
								children: ["Last poll ", fmtTime(result.fetchedAt)]
							})
						]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
						className: "grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_7rem_auto_auto_auto]",
						onSubmit: (e) => {
							e.preventDefault();
							onRerun();
						},
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
								className: cn(inputClass, "font-mono"),
								value: mac,
								onChange: (e) => onMac(e.target.value),
								"aria-label": "Client MAC"
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
								className: inputClass,
								value: duration,
								onChange: (e) => onDuration(e.target.value),
								"aria-label": "Lookback",
								children: [
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: "1h",
										children: "1h"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: "6h",
										children: "6h"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: "1d",
										children: "1d"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: "1w",
										children: "1w"
									})
								]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Button, {
								type: "submit",
								disabled: busy,
								className: "w-full lg:w-auto",
								children: busy ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(LoaderCircle, { className: "size-4 animate-spin" }) : "Refresh"
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)(Button, {
								type: "button",
								variant: live ? "secondary" : "primary",
								className: "w-full lg:w-auto",
								onClick: () => onLive(!live),
								children: [live ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Pause, { className: "size-4" }) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Radio, { className: "size-4" }), live ? "Stop live" : "Live monitor"]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
								className: inputClass,
								value: liveSec,
								onChange: (e) => onLiveSec(Number(e.target.value)),
								"aria-label": "Poll interval",
								disabled: !live,
								children: [
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: 15,
										children: "every 15s"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: 30,
										children: "every 30s"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
										value: 60,
										children: "every 60s"
									})
								]
							})
						]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex flex-wrap items-center justify-between gap-2",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
							className: "text-xs text-subtle",
							children: "Live mode re-queries per-MAC stats/events only. Auto-pauses on Mist 429."
						}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Button, {
							type: "button",
							variant: "ghost",
							className: "px-3",
							onClick: onBack,
							children: "Back"
						})]
					})
				]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: cn("min-w-0 rounded-2xl border bg-surface p-4 sm:p-5", result.verdict.label === "Critical" ? "border-crit/50 metric-crit" : "border-border"),
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex flex-wrap items-center gap-3",
						children: [result.verdict.label === "Healthy" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(CircleCheck, { className: "size-5 text-good" }) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(TriangleAlert, { className: cn("size-5", verdictTone) }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
							className: cn("text-lg font-semibold", verdictTone),
							children: [
								result.verdict.label,
								" · score ",
								result.verdict.score
							]
						})]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "mt-2 text-sm",
						children: result.verdict.primaryCause
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
						className: "mt-3 grid gap-1 text-sm text-muted",
						children: result.verdict.notes.map((n) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: ["— ", n] }, n))
					})
				]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
					className: "text-sm font-semibold uppercase tracking-wide text-subtle",
					children: "Correlated causes"
				}), !result.verdict.correlations.length ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "mt-3 text-sm text-muted",
					children: "No multi-signal pattern in this window."
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
					className: "mt-3 grid gap-3",
					children: result.verdict.correlations.map((c) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)(CorrelationCard, { c }, c.id))
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "grid min-w-0 gap-3 grid-cols-2 lg:grid-cols-4",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Metric, {
						label: "RSSI",
						value: s?.rssi != null ? `${s.rssi} dBm` : "—",
						hint: "Good ≥ −65 · Crit < −75",
						band: rb
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Metric, {
						label: "SNR",
						value: s?.snr != null ? `${s.snr} dB` : "—",
						hint: "Good ≥ 25 · Crit < 15",
						band: sb
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Metric, {
						label: "Disconnects",
						value: String(disconnects),
						hint: `Window ${result.duration}`,
						band: disconnects >= 3 ? "crit" : disconnects >= 1 ? "warn" : "good"
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Metric, {
						label: "TX retries",
						value: s?.txRetries != null ? String(s.txRetries) : "—",
						hint: s?.dualBand ? "dual-band client" : "retries",
						band: s?.txRetries != null && s.txRetries >= 80 ? rb === "good" ? "warn" : "crit" : "unknown"
					})
				]
			}),
			live || samples.length > 1 ? /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "grid min-w-0 gap-3 sm:grid-cols-2",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "rounded-2xl border border-border bg-surface p-4",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-xs uppercase tracking-wide text-subtle",
						children: "RSSI over live polls"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Sparkline, {
						samples,
						field: "rssi"
					})]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "rounded-2xl border border-border bg-surface p-4",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-xs uppercase tracking-wide text-subtle",
						children: "SNR over live polls"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Sparkline, {
						samples,
						field: "snr"
					})]
				})]
			}) : null,
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "grid min-w-0 gap-4 lg:grid-cols-2",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
						className: "text-sm font-semibold uppercase tracking-wide text-subtle",
						children: "Identity / radio"
					}), !s ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "mt-3 text-sm text-muted",
						children: "No live stats for this MAC on the site."
					}) : /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("dl", {
						className: "mt-3 grid grid-cols-[minmax(5.5rem,7rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm",
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Hostname",
								v: s.hostname
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "User",
								v: s.username
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Vendor",
								v: s.manufacture
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "OS / model",
								v: [s.os, s.model].filter(Boolean).join(" / ")
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "SSID",
								v: s.ssid
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "VLAN",
								v: s.vlan != null ? String(s.vlan) : null
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "IP",
								v: s.ip
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "AP",
								v: s.ap
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Band / ch",
								v: [s.band, s.channel].filter((x) => x != null && x !== "").join(" / ")
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Protocol",
								v: s.proto
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Key mgmt",
								v: s.keyMgmt
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Tx / Rx",
								v: [s.txRate, s.rxRate].every((x) => x == null) ? null : `${s.txRate ?? "—"} / ${s.rxRate ?? "—"}`
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Retries",
								v: s.txRetries != null ? `${s.txRetries} tx / ${s.rxRetries ?? "—"} rx` : null
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Uptime",
								v: fmtDuration(s.uptime)
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Last seen",
								v: fmtTime(s.lastSeen)
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Row, {
								k: "Bytes",
								v: `${fmtBytes(s.txBytes)} / ${fmtBytes(s.rxBytes)}`
							})
						]
					})]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
					className: "min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
						className: "text-sm font-semibold uppercase tracking-wide text-subtle",
						children: "Sessions"
					}), !result.sessions.length ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "mt-3 text-sm text-muted",
						children: "No session records in this window."
					}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
						className: "mt-3 divide-y divide-border",
						children: result.sessions.slice(0, 8).map((sess, i) => {
							const short = sess.duration != null && sess.duration < 60;
							return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
								className: "py-2.5 text-sm",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
									className: "flex items-center justify-between gap-2",
									children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
										className: "min-w-0 truncate font-mono text-xs text-muted",
										children: sess.ap || "AP —"
									}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
										className: cn("shrink-0 font-mono tabular-nums", short ? "text-crit" : "text-fg"),
										children: fmtDuration(sess.duration)
									})]
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
									className: "text-xs text-subtle",
									children: [
										sess.ssid,
										" · ",
										sess.band || "band —",
										" · ",
										fmtTime(sess.connect),
										sess.disconnect ? ` → ${fmtTime(sess.disconnect)}` : " (open)"
									]
								})]
							}, `${sess.ap}-${sess.connect}-${i}`);
						})
					})]
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("h2", {
					className: "flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-subtle",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(Activity, { className: "size-4" }), " Event timeline"]
				}), !result.events.length ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "mt-3 text-sm text-muted",
					children: "No client events returned for this window."
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
					className: "mt-3 space-y-2",
					children: result.events.slice(0, 40).map((ev, i) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
						className: cn("rounded-lg border px-3 py-2", ev.negative ? "border-crit/35 bg-surface-2" : "border-border"),
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
								className: "flex flex-wrap items-baseline justify-between gap-2",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
									className: cn("break-all font-mono text-xs", ev.negative ? "text-crit" : "text-good"),
									children: [
										ev.negative ? "FAIL" : "OK",
										" · ",
										ev.type
									]
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
									className: "font-mono text-xs text-subtle tabular-nums",
									children: fmtTime(ev.timestamp)
								})]
							}),
							ev.text ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
								className: "mt-1 text-sm",
								children: ev.text
							}) : null,
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
								className: "mt-1 break-words text-xs text-muted",
								children: [
									"AP ",
									ev.ap || "—",
									" · ",
									ev.ssid || "SSID —",
									" · ",
									ev.band || "band —",
									ev.channel != null && ev.channel !== "" ? ` / ch ${ev.channel}` : "",
									describeReason(ev.reason ?? void 0) ? ` · ${describeReason(ev.reason ?? void 0)}` : ""
								]
							})
						]
					}, `${ev.timestamp}-${ev.type}-${i}`))
				})]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "min-w-0 rounded-2xl border border-border bg-surface p-4 sm:p-5",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
					className: "text-sm font-semibold uppercase tracking-wide text-subtle",
					children: "Marvis"
				}), result.marvisUnavailable || !result.marvisText ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "mt-3 text-sm text-muted",
					children: "Marvis Troubleshoot not available (no subscription, empty result, or API error). Events and RF still stand on their own."
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("pre", {
					className: "mt-3 max-w-full overflow-x-auto rounded-lg bg-surface-2 p-3 text-xs leading-relaxed text-fg whitespace-pre-wrap break-words",
					children: result.marvisText
				})]
			})
		]
	});
}
function CorrelationCard({ c }) {
	const tone = c.severity === "crit" ? "border-crit/40" : c.severity === "warn" ? "border-warn/40" : "border-border";
	const badge = c.severity === "crit" ? "text-crit" : c.severity === "warn" ? "text-warn" : "text-muted";
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
		className: cn("rounded-xl border bg-surface-2 px-3 py-3 sm:px-4", tone),
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: "flex flex-wrap items-baseline justify-between gap-2",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: cn("text-sm font-medium", badge),
				children: c.title
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "text-[11px] uppercase tracking-wide text-subtle",
				children: [
					c.confidence,
					" · ",
					c.severity
				]
			})]
		}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
			className: "mt-1.5 text-sm text-muted",
			children: c.evidence
		})]
	});
}
function Row({ k, v }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("dt", {
		className: "text-subtle",
		children: k
	}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("dd", {
		className: "min-w-0 break-all font-mono text-xs sm:text-sm",
		children: v || "—"
	})] });
}
function Home() {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ConsoleApp, {});
}
//#endregion
export { Home as component };
