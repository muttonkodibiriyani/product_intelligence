/**
 * The only way the model reaches data (design §4, §6):
 * - a fixed allowlist of read-only tools;
 * - a role check;
 * - strict input parsing;
 * - one API call carrying the user's ID token;
 * - envelope validation and fail-closed sanitising;
 * - a size cap;
 * - a citation built from the envelope meta.
 * Anything unexpected becomes a typed error result, never free text the model could follow.
 */
import type { z } from "zod";

import { ApiError, type ApiRequest, type MetricApi } from "../api/client.js";
import {
  type Bilingual,
  type Evidence,
  EnvelopeSchema,
  type NotEnoughDataReason,
} from "../api/envelope.js";
import { type Sanitised, sanitiseData } from "../guard/sanitise.js";
import { evidenceUrl } from "../guard/untrusted.js";
import { type AnyToolDef, type CallerContext, ROLES, type Role } from "./types.js";

/** Tool results larger than this are refused rather than truncated mid-structure. */
export const MAX_RESULT_CHARS = 16_000;

export type ToolErrorCode =
  | "unknown_tool"
  | "forbidden"
  | "unauthenticated"
  | "invalid_input"
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
  readonly apiVersion: string | null;
  readonly datasetGeneration: string;
  readonly cutoff: string;
  readonly market: string;
  readonly currency: string;
  readonly filters: Readonly<Record<string, unknown>>;
  readonly cohort: { readonly description: string; readonly n: number };
}

export interface ToolEnvelope {
  readonly status: "ok" | "not_enough_data";
  readonly data?: Sanitised;
  readonly notEnoughData?: { readonly reason: NotEnoughDataReason; readonly detail: Bilingual };
  readonly citation: Citation;
  readonly caveats: readonly Bilingual[];
  readonly evidence: readonly Evidence[];
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
  return "upstream_unavailable";
}

const API_ERROR_MESSAGES: Record<ToolErrorCode, string> = {
  unknown_tool: "No such tool.",
  forbidden: "This data is not available to your role.",
  unauthenticated: "Your session has expired; sign in again.",
  invalid_input: "The data service rejected these inputs.",
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
    const { meta, cohort, caveats } = envelope.data;
    const { evidenceHosts } = this.config;
    const result: ToolEnvelope = {
      status: envelope.data.status,
      ...(envelope.data.status === "ok"
        ? { data: sanitiseData(envelope.data.data, evidenceHosts) }
        : {
            notEnoughData: {
              reason: envelope.data.reason ?? "no_match",
              detail: envelope.data.detail ?? { en: "", ar: "" },
            },
          }),
      citation: {
        tool: tool.name,
        toolVersion: tool.version,
        apiVersion: meta.apiVersion ?? null,
        datasetGeneration: meta.generation,
        cutoff: meta.cutoff,
        market: meta.market,
        currency: meta.currency,
        filters: input,
        cohort,
      },
      caveats,
      // Defence in depth: the API strips admin-only fields for viewers; strip them again here.
      evidence: envelope.data.evidence.map(({ runId, source, ...item }) => ({
        ...item,
        url: evidenceUrl(item.url, evidenceHosts),
        ...(caller.role === "admin" && runId !== undefined ? { runId } : {}),
        ...(caller.role === "admin" && source !== undefined ? { source } : {}),
      })),
    };
    if (JSON.stringify(result).length > MAX_RESULT_CHARS) {
      return error(name, "output_too_large", API_ERROR_MESSAGES.output_too_large);
    }
    return result;
  }
}
