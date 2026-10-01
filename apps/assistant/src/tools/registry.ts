/**
 * The only way the model reaches data (design §4, §6):
 * - a fixed allowlist of read-only tools;
 * - a role check;
 * - strict input parsing;
 * - one API call carrying the user's ID token;
 * - envelope validation and fail-closed sanitising (evidence links inside `data` are filtered
 *   to allowlisted https hosts; admin-only evidence fields are dropped for viewers);
 * - a size cap;
 * - a citation built from the envelope meta;
 * - API prose (caveats, not-enough-data detail, cohort description) wrapped as `{untrusted}`,
 *   because the API may interpolate retailer text (brand, category) into it.
 * Anything unexpected becomes a typed error result, never free text the model could follow.
 */
import type { z } from "zod";

import { ApiError, type ApiRequest, type MetricApi } from "../api/client.js";
import { type Untrusted, untrusted } from "../guard/untrusted.js";
import { type Bilingual, EnvelopeSchema, type NotEnoughDataReason } from "../api/envelope.js";
import { type Sanitised, sanitiseData } from "../guard/sanitise.js";
import { type AnyToolDef, type CallerContext, ROLES, type Role } from "./types.js";

/** Tool results larger than this are refused rather than truncated mid-structure. */
export const MAX_RESULT_CHARS = 16_000;

export type ToolErrorCode =
  | "unknown_tool"
  | "forbidden"
  | "unauthenticated"
  | "invalid_input"
  | "not_found"
  | "rate_limited"
  | "stale_cursor"
  | "upstream_unavailable"
  | "upstream_invalid"
  | "output_too_large";

export interface ToolError {
  readonly status: "error";
  readonly tool: string;
  readonly code: ToolErrorCode;
  readonly message: string;
}

export interface Citation {
  readonly tool: string;
  readonly toolVersion: string;
  readonly apiVersion: string;
  readonly metricVersion: string;
  readonly datasetGeneration: string;
  readonly cutoff: string;
  readonly market: string;
  readonly currency: string;
  /** The tool's parsed input (what the model asked for). */
  readonly filters: Readonly<Record<string, unknown>>;
  /** Null for endpoints without a cohort (search, product, coverage, launches...). */
  readonly cohort: { readonly description: Untrusted; readonly n: number } | null;
}

/** API prose in both languages, each side wrapped as untrusted data. */
export interface UntrustedBilingual {
  readonly en: Untrusted;
  readonly ar: Untrusted;
}

/** Longest API prose passed to the model, per language. */
export const PROSE_MAX_CHARS = 500;

function prose(text: Bilingual): UntrustedBilingual {
  return { en: untrusted(text.en, PROSE_MAX_CHARS), ar: untrusted(text.ar, PROSE_MAX_CHARS) };
}

/** A caveat: its machine code plus the API's text in both languages, wrapped. */
export interface Caveat extends UntrustedBilingual {
  readonly code: string;
}

export interface ToolEnvelope {
  readonly status: "ok" | "not_enough_data";
  readonly data?: Sanitised;
  readonly notEnoughData?: {
    readonly reason: NotEnoughDataReason;
    readonly detail: UntrustedBilingual;
  };
  readonly citation: Citation;
  readonly caveats: readonly Caveat[];
}

export type ToolResult = ToolEnvelope | ToolError;

function rank(role: Role): number {
  return ROLES.indexOf(role);
}

function error(tool: string, code: ToolErrorCode, message: string): ToolError {
  return { status: "error", tool, code, message };
}

function apiErrorCode(status: number): ToolErrorCode {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 422) return "invalid_input";
  if (status === 404) return "not_found";
  if (status === 409) return "stale_cursor";
  if (status === 429) return "rate_limited";
  return "upstream_unavailable";
}

const API_ERROR_MESSAGES: Record<ToolErrorCode, string> = {
  unknown_tool: "No such tool.",
  forbidden: "This data is not available to your role.",
  unauthenticated: "Your session has expired; sign in again.",
  invalid_input: "The data service rejected these inputs.",
  not_found: "Nothing has this id.",
  rate_limited: "Too many requests; wait a moment and try again.",
  stale_cursor: "The data was refreshed; run the search again without a cursor.",
  upstream_unavailable: "The data service is unavailable right now.",
  upstream_invalid: "The data service returned an unexpected result.",
  output_too_large: "Result too large; narrow the filters or lower limit.",
};

export class ToolRegistry {
  private readonly tools: ReadonlyMap<string, AnyToolDef>;

  constructor(
    tools: readonly AnyToolDef[],
    private readonly api: MetricApi,
    private readonly config: { readonly evidenceHosts: readonly string[] },
  ) {
    const byName = new Map<string, AnyToolDef>();
    for (const tool of tools) {
      if (byName.has(tool.name)) throw new Error(`duplicate tool ${tool.name}`);
      byName.set(tool.name, tool);
    }
    this.tools = byName;
  }

  /** Tools this caller may see; the model is never offered a tool it cannot call. */
  available(caller: CallerContext): AnyToolDef[] {
    return [...this.tools.values()].filter((tool) => rank(caller.role) >= rank(tool.minRole));
  }

  async run(
    name: string,
    rawInput: unknown,
    caller: CallerContext,
    idToken: string,
  ): Promise<ToolResult> {
    const tool = this.tools.get(name);
    if (!tool) return error(name, "unknown_tool", API_ERROR_MESSAGES.unknown_tool);
    if (rank(caller.role) < rank(tool.minRole)) {
      return error(name, "forbidden", "This tool is not available to your role.");
    }
    const parsed: z.SafeParseReturnType<unknown, unknown> = tool.input.safeParse(rawInput ?? {});
    if (!parsed.success) {
      const issues = parsed.error.issues
        .slice(0, 5)
        .map((issue) => `${issue.path.join(".") || "input"}: ${issue.message}`);
      return error(name, "invalid_input", issues.join("; "));
    }
    const input = parsed.data as Record<string, unknown>;
    // Safe: `input` is exactly what this tool's own schema produced.
    const request = (tool.request as (value: unknown) => ApiRequest)(input);
    let body: unknown;
    try {
      body = await this.api.call(request, idToken);
    } catch (cause) {
      if (!(cause instanceof ApiError)) throw cause;
      const code = apiErrorCode(cause.status);
      return error(name, code, API_ERROR_MESSAGES[code]);
    }
    const envelope = EnvelopeSchema.safeParse(body);
    if (!envelope.success) {
      return error(name, "upstream_invalid", API_ERROR_MESSAGES.upstream_invalid);
    }
    const { meta, cohort, caveats, data } = envelope.data;
    const result: ToolEnvelope = {
      status: envelope.data.status,
      // not_enough_data may still carry rows (e.g. compare below the cohort minimum).
      ...(data === undefined || data === null
        ? {}
        : {
            data: sanitiseData(data, {
              evidenceHosts: this.config.evidenceHosts,
              admin: caller.role === "admin",
            }),
          }),
      ...(envelope.data.status === "ok"
        ? {}
        : {
            notEnoughData: {
              reason: envelope.data.reason ?? "no_match",
              detail: prose(envelope.data.detail ?? { en: "", ar: "" }),
            },
          }),
      citation: {
        tool: tool.name,
        toolVersion: tool.version,
        apiVersion: meta.apiVersion,
        metricVersion: meta.metricVersion,
        datasetGeneration: meta.generation,
        cutoff: meta.cutoff,
        market: meta.market,
        currency: meta.currency,
        filters: input,
        cohort:
          cohort === null || cohort === undefined
            ? null
            : { description: untrusted(cohort.description, PROSE_MAX_CHARS), n: cohort.n },
      },
      caveats: caveats.map(({ code, ...text }) => ({ code, ...prose(text) })),
    };
    if (JSON.stringify(result).length > MAX_RESULT_CHARS) {
      return error(name, "output_too_large", API_ERROR_MESSAGES.output_too_large);
    }
    return result;
  }
}
