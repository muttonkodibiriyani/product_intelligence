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
import {
  type Bilingual,
  EnvelopeSchema,
  NOT_ENOUGH_DATA_REASONS,
  type NotEnoughDataReason,
} from "../api/envelope.js";
import { type Sanitised, sanitiseData } from "../guard/sanitise.js";
import { type AnyToolDef, type CallerContext, ROLES, type Role, type ToolView } from "./types.js";

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

/**
 * A caveat: its machine code, the API's text in both languages (wrapped) and its sanitised
 * parameters. Only the parameters can supply numbers the answer quotes; the text never does.
 */
export interface Caveat extends UntrustedBilingual {
  readonly code: string;
  readonly params?: Sanitised;
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

/**
 * A limited list (`truncated: true`): the number of rows actually returned, so the answer can
 * quote "top N of total" and the verifier finds N in the result. Null when nothing was cut.
 */
export function truncation(
  data: unknown,
  listKey: string | undefined,
): { readonly shown: number; readonly total: number } | null {
  if (listKey === undefined || typeof data !== "object" || data === null) return null;
  const record = data as Record<string, unknown>;
  const rows = record[listKey];
  const total = record.total;
  if (record.truncated !== true || !Array.isArray(rows) || typeof total !== "number") return null;
  return { shown: rows.length, total };
}

function truncatedCaveat({ shown, total }: { shown: number; total: number }): Caveat {
  const [n, of] = [String(shown), String(total)];
  return {
    code: "truncated",
    ...prose({
      en: `Only the first ${n} of ${of} rows are listed, the row limit. Any summary is computed over all rows, not only the listed ones; its n is what it counted.`,
      ar: `تُعرض أول ${n} من أصل ${of} صفًا فقط بسبب حد الصفوف. أي ملخص محسوب على جميع الصفوف لا على المعروضة فقط، وقيمة n فيه هي ما احتُسب.`,
    }),
  };
}

/**
 * Caveats listed per result. Upstream caveats beyond the room left by `extra` (the row-limit
 * caveat, always kept) collapse into one assistant-side `caveats_truncated`; not a pi_api code.
 */
export const MAX_CAVEATS = 20;

function listedCaveats(upstream: readonly Caveat[], extra: readonly Caveat[]): Caveat[] {
  const room = MAX_CAVEATS - extra.length;
  if (upstream.length <= room) return [...upstream, ...extra];
  const more = String(upstream.length - (room - 1));
  return [
    ...upstream.slice(0, room - 1),
    {
      code: "caveats_truncated",
      ...prose({
        en: `${more} more caveats are not listed.`,
        ar: `هناك ${more} تنبيهات أخرى غير معروضة.`,
      }),
    },
    ...extra,
  ];
}

function withShown(data: Sanitised, cut: { readonly shown: number } | null): Sanitised {
  if (cut === null || typeof data !== "object" || data === null || Array.isArray(data)) return data;
  return { ...data, shown: cut.shown };
}

function rank(role: Role): number {
  return ROLES.indexOf(role);
}

function error(tool: string, code: ToolErrorCode, message: string): ToolError {
  return { status: "error", tool, code, message };
}

function apiErrorCode(status: number, byId: boolean): ToolErrorCode {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 400 || status === 422) return "invalid_input";
  if (status === 404) return byId ? "not_found" : "upstream_unavailable";
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

/** Said when a tool's view finds its part of the response withheld by the service. */
export const WITHHELD_DETAIL: Bilingual = {
  en: "The data service withheld this part of the data, so it is not measured (not zero).",
  ar: "حجبت خدمة البيانات هذا الجزء، لذا فهو غير مقيس (وليس صفرًا).",
};

/** A view's withheld reason, kept only when it is one of the service's closed reasons. */
function withheldReason(reason: string | undefined): NotEnoughDataReason | undefined {
  if (reason === undefined) return undefined;
  return NOT_ENOUGH_DATA_REASONS.find((known) => known === reason) ?? "no_match";
}

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

  /** Whether `name` is a declared tool (any role). */
  has(name: string): boolean {
    return this.tools.has(name);
  }

  /** The key of a tool's row list (`listKey`), if it returns one. */
  listKey(name: string): string | undefined {
    return this.tools.get(name)?.listKey;
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
      const code = apiErrorCode(cause.status, tool.byId === true);
      return error(name, code, API_ERROR_MESSAGES[code]);
    }
    const envelope = EnvelopeSchema.safeParse(body);
    if (!envelope.success) {
      return error(name, "upstream_invalid", API_ERROR_MESSAGES.upstream_invalid);
    }
    const { meta, cohort, caveats } = envelope.data;
    const view =
      tool.view && envelope.data.data !== undefined && envelope.data.data !== null
        ? (tool.view as (data: unknown, value: unknown) => ToolView)(envelope.data.data, input)
        : undefined;
    const data = view ? view.data : envelope.data.data;
    const withheld = envelope.data.status === "ok" ? withheldReason(view?.withheld) : undefined;
    const status = withheld === undefined ? envelope.data.status : "not_enough_data";
    const cut = truncation(data, tool.listKey);
    const sanitiseOptions = {
      evidenceHosts: this.config.evidenceHosts,
      admin: caller.role === "admin",
    };
    const result: ToolEnvelope = {
      status,
      // not_enough_data may still carry rows (e.g. compare below the cohort minimum).
      ...(data === undefined || data === null
        ? {}
        : {
            data: withShown(sanitiseData(data, sanitiseOptions), cut),
          }),
      ...(status === "ok"
        ? {}
        : withheld !== undefined
          ? { notEnoughData: { reason: withheld, detail: prose(WITHHELD_DETAIL) } }
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
      caveats: listedCaveats(
        caveats.map(({ code, params, ...text }) => ({
          code,
          ...prose(text),
          params: sanitiseData(params, sanitiseOptions),
        })),
        cut ? [truncatedCaveat(cut)] : [],
      ),
    };
    if (JSON.stringify(result).length > MAX_RESULT_CHARS) {
      return error(name, "output_too_large", API_ERROR_MESSAGES.output_too_large);
    }
    return result;
  }
}
