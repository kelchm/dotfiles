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

const QWEN = {
	reasoning: true,
	input: ["text", "image"],
	contextWindow: 512000,
	maxTokens: 32000,
	// The server has none, low, medium and xhigh. It renders minimal as low, and
	// high and max as xhigh, so the duplicate Pi levels are hidden.
	thinkingLevelMap: {
		off: "none",
		minimal: null,
		low: "low",
		medium: "medium",
		high: null,
		xhigh: null,
		max: "max",
	},
} as const;

// /v1/models reports only an ID, so limits and thinking controls are kept here.
const KNOWN = {
	"GLM-5.3-Flash-EXL3": {
		name: "GLM-5.3-Flash",
		reasoning: true,
		input: ["text", "image"],
		contextWindow: 850000,
		maxTokens: 32000,
		// GLM has low, high and max, plus none to disable thinking. The server
		// renders medium exactly like max, so the other Pi levels are hidden.
		thinkingLevelMap: {
			off: "none",
			minimal: null,
			low: "low",
			medium: null,
			high: "high",
			xhigh: null,
			max: "max",
		},
	},
	// The Qwen kit serves a 1,048,576 window, but a 999,874-token prompt stalled
	// both ranks on October 8 where 524,135 completed, so Pi compacts below that.
	"Qwen3.8-Flash-Next": { name: "Qwen3.8-Flash-Next", ...QWEN },
	"Qwen3.8-Flash-Next-INT4-AR": { name: "Qwen3.8-Flash-Next INT4-AR", ...QWEN },
} as const;

// A served model with no entry above still appears, with limits small enough to be safe.
const UNKNOWN = { reasoning: false, input: ["text"], contextWindow: 128000, maxTokens: 8192 } as const;

function describe(id: string) {
	const known = KNOWN[id as keyof typeof KNOWN];
	return { id, name: id, ...(known ?? UNKNOWN), cost: FREE };
}

async function servedModels(signal?: AbortSignal) {
	const timeout = AbortSignal.timeout(DISCOVERY_TIMEOUT_MS);
	const response = await fetch(`${BASE_URL}/models`, {
		signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
	});
	if (!response.ok) throw new Error(`${BASE_URL}/models returned HTTP ${response.status}`);
	const body = (await response.json()) as { data?: { id?: unknown }[] };
	const ids = (body.data ?? []).map((model) => model.id).filter((id): id is string => typeof id === "string");
	return ids.map(describe);
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
