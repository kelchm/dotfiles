/**
 * Local inference on the DGX Sparks (home-lab repo: sparks/inference/sparkrun/README.md).
 * TensorFold serves OpenAI-compatible chat completions, unauthenticated on the trusted LAN.
 *
 * The Sparks serve one model at a time and it changes between trials, so the
 * provider lists whatever /v1/models reports instead of a fixed entry. Pi's
 * startup model then follows the served one, and callers that defer to Pi's
 * default (T3 Code's "Pi default") need no change when the model is swapped.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BASE_URL = process.env.SPARK_BASE_URL ?? "http://10.32.21.31:8888/v1";
// Every Pi start waits on this, including on machines that cannot reach the Sparks.
const DISCOVERY_TIMEOUT_MS = 1500;

const FREE = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };

// Pi's thinking levels above off. The server names its efforts the same way.
const LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;

type Level = "off" | (typeof LEVELS)[number];
type LevelMap = Record<Level, string | null>;

type Entry = { name?: string; contextWindow?: number; thinkingLevelMap?: LevelMap };

// TensorFold reports the window and thinking levels in /v1/models, so only
// what it cannot know is kept here. A server that reports neither falls back
// to these values.
const KNOWN: Record<string, Entry> = {
	// Not served lately, and its Python server may report nothing beyond the ID.
	"GLM-5.3-Flash-EXL3": {
		name: "GLM-5.3-Flash",
		contextWindow: 850000,
		// GLM has low, high and max, plus none to disable thinking. The server
		// renders medium exactly like max, so the other Pi levels are hidden.
		thinkingLevelMap: { off: "none", minimal: null, low: "low", medium: null, high: "high", xhigh: null, max: "max" },
	},
	// The Qwen kit serves a 1,048,576 window, but a 999,874-token prompt stalled
	// both ranks on October 8 where 524,135 completed, so Pi compacts below that.
	"Qwen3.8-Flash-Next": { name: "Qwen3.8-Flash-Next", contextWindow: 512000 },
	"Qwen3.8-Flash-Next-INT4-AR": { name: "Qwen3.8-Flash-Next INT4-AR", contextWindow: 512000 },
};

// A model whose server reports no window still appears, with one small enough to be safe.
const FALLBACK_CONTEXT_WINDOW = 128000;

type Served = {
	id?: unknown;
	context_length?: unknown;
	reasoning?: { supported_efforts?: unknown };
};

// Offers exactly the server's efforts, each as the Pi level of the same name and
// none as off. Names Pi has no level for are dropped.
function levelMap(efforts: unknown): LevelMap | undefined {
	if (!Array.isArray(efforts)) return undefined;
	const offered = (level: string) => (efforts.includes(level) ? level : null);
	const map = { off: offered("none") } as LevelMap;
	for (const level of LEVELS) map[level] = offered(level);
	return map;
}

function describe(served: Served & { id: string }) {
	const known = KNOWN[served.id] ?? {};
	const reported = typeof served.context_length === "number" ? served.context_length : Infinity;
	const contextWindow = Math.min(reported, known.contextWindow ?? Infinity);
	const thinkingLevelMap = levelMap(served.reasoning?.supported_efforts) ?? known.thinkingLevelMap;
	// Pi cannot ask for thinking without naming a level, so a model with no
	// levels above off gets no thinking control and runs at the server's default.
	const reasoning = thinkingLevelMap !== undefined && LEVELS.some((level) => thinkingLevelMap[level] !== null);
	return {
		id: served.id,
		name: known.name ?? served.id,
		reasoning,
		...(reasoning && { thinkingLevelMap }),
		// /v1/models does not say whether images are accepted. A text-only launch
		// refuses the first image with a clear error, so a wrong guess fails loudly.
		input: ["text", "image"],
		contextWindow: Number.isFinite(contextWindow) ? contextWindow : FALLBACK_CONTEXT_WINDOW,
		// 0 makes Pi send no output limit, so the server's default applies and is
		// reduced to fit the room left in the window.
		maxTokens: 0,
		cost: FREE,
	};
}

async function servedModels(signal?: AbortSignal) {
	const timeout = AbortSignal.timeout(DISCOVERY_TIMEOUT_MS);
	const response = await fetch(`${BASE_URL}/models`, {
		signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
	});
	if (!response.ok) throw new Error(`${BASE_URL}/models returned HTTP ${response.status}`);
	const body = (await response.json()) as { data?: Served[] };
	return (body.data ?? []).filter((model): model is Served & { id: string } => typeof model.id === "string").map(describe);
}

export default async function (pi: ExtensionAPI) {
	// Off the home network, or with the Sparks down, there is nothing to offer.
	const models = await servedModels().catch(() => []);
	if (models.length === 0) return;
	pi.registerProvider("spark", {
		baseUrl: BASE_URL,
		api: "openai-completions",
		// The server ignores the key; Pi needs one to list the model.
		apiKey: "none",
		models,
		refreshModels: (context) => servedModels(context.signal),
	});
}
