/**
 * The chat flow (design §5): one question in, one verified answer out.
 *
 * 1. The meter opens the question (kill switch, config, per-user daily cap).
 * 2. Tool loop: every model call goes through `Meter.call`; every tool call the model proposes
 *    goes through the registry with the caller's ID token. At most `maxToolCalls` tool calls.
 * 3. The answer is cleaned (no links, images or HTML; only known product tokens) and its numbers
 *    are checked against the tool output. On failure it is regenerated once, without tools;
 *    if it fails again the user gets the fallback note and the raw tool results instead.
 *
 * Structured fields (citations, product ids, not-enough-data reasons) are assembled here from
 * tool results, never taken from model text.
 */
import type { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";

import { limitsOf } from "../meter/config.js";
import { type Meter, MeterRefusal, type Question, type RefusalCode } from "../meter/meter.js";
import { formatUsd } from "../meter/prices.js";
import { cleanAnswer } from "../guard/answer.js";
import { verifyAnswerNumbers } from "../guard/verifier.js";
import type {
  Citation,
  ToolEnvelope,
  ToolRegistry,
  ToolResult,
  UntrustedBilingual,
} from "../tools/registry.js";
import type { AnyToolDef, CallerContext } from "../tools/types.js";
import {
  type ChatModel,
  type ModelReply,
  type ModelRequest,
  type ToolSpec,
  type Turn,
  promptTokenBound,
} from "./model.js";
import {
  type Locale,
  PROMPT_VERSION,
  TOOL_BUDGET_SPENT,
  systemPrompt,
  verifierRetry,
} from "./prompt.js";

export const MAX_TOOL_CALLS = 6;
export const MAX_QUESTION_CHARS = 2_000;
export const MAX_HISTORY_TURNS = 10;
export const TEMPERATURE = 0.2;

export interface HistoryTurn {
  readonly role: "user" | "model";
  readonly text: string;
}

export interface ChatInput {
  readonly question: string;
  readonly locale: Locale;
  /** Earlier turns of this thread, text only (no tool results carry over). */
  readonly history?: readonly HistoryTurn[];
}

export type AnswerStatus =
  /** Verified answer. */
  | "answered"
  /** The verifier failed twice: fallback note plus raw tool results. */
  | "unverified"
  /** No model call was possible (kill switch, caps, prompt too large, bad input). */
  | "unavailable";

export interface ToolCallRecord {
  readonly name: string;
  readonly args: unknown;
  readonly status: ToolResult["status"];
  readonly code?: string;
}

export interface ChatAnswer {
  readonly status: AnswerStatus;
  /** Why the answer is unavailable or unverified (meter refusal or flow code). */
  readonly code?: RefusalCode | FlowCode;
  readonly answerMd: string;
  readonly language: Locale;
  readonly promptVersion: string;
  readonly model: string | null;
  /** True when the first answer passed the verifier (an eval metric). */
  readonly firstPassVerified: boolean;
  readonly citations: readonly Citation[];
  readonly caveats: readonly UntrustedBilingual[];
  readonly productIds: readonly string[];
  readonly notEnoughData: readonly {
    readonly tool: string;
    readonly reason: string;
    readonly detail: UntrustedBilingual;
  }[];
  readonly toolCalls: readonly ToolCallRecord[];
  /** Successful and not-enough-data tool results, for the UI's tables (unverified fallback). */
  readonly toolResults: readonly ToolEnvelope[];
  readonly modelCalls: number;
  /** Metered cost of this question, USD decimal text. */
  readonly costUsd: string;
}

export type FlowCode =
  "invalid_question" | "prompt_too_large" | "model_error" | "prompt_version_mismatch";

export const FALLBACK_NOTE: Record<Locale, string> = {
  en: "I could not produce a verified summary. The tool results are shown below.",
  ar: "تعذّر إعداد ملخص موثّق. نتائج الأدوات معروضة أدناه.",
};

const UNAVAILABLE_NOTE: Record<Locale, string> = {
  en: "The assistant is not available right now. Please try again later.",
  ar: "المساعد غير متاح حالياً. يرجى المحاولة لاحقاً.",
};

export function toolSpec(tool: AnyToolDef): ToolSpec {
  return {
    name: tool.name,
    description: tool.description,
    parameters: zodToJsonSchema(tool.input as z.ZodType, {
      $refStrategy: "none",
      target: "openApi3",
    }),
  };
}

/** Product ids the tools returned: `id`/`productId` strings in data and evidence. */
export function knownProductIds(results: readonly ToolEnvelope[]): Set<string> {
  const ids = new Set<string>();
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) {
      value.forEach(visit);
    } else if (typeof value === "object" && value !== null && !("untrusted" in value)) {
      for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
        if ((key === "id" || key === "productId") && typeof child === "string") ids.add(child);
        else visit(child);
      }
    }
  };
  for (const result of results) {
    visit(result.data);
    visit(result.evidence);
  }
  return ids;
}

interface FlowState {
  readonly turns: Turn[];
  readonly results: ToolEnvelope[];
  readonly records: ToolCallRecord[];
  modelCalls: number;
  toolCalls: number;
}

export class ChatFlow {
  constructor(
    private readonly deps: {
      readonly meter: Meter;
      readonly model: ChatModel;
      readonly registry: ToolRegistry;
      readonly label?: string;
      readonly maxToolCalls?: number;
    },
  ) {}

  async answer(input: ChatInput, caller: CallerContext, idToken: string): Promise<ChatAnswer> {
    const { locale } = input;
    const question = input.question.trim();
    if (question.length === 0 || question.length > MAX_QUESTION_CHARS) {
      return this.unavailable(locale, "invalid_question", null, null);
    }

    let open: Question;
    try {
      open = await this.deps.meter.startQuestion(caller, this.deps.label ?? "chat");
    } catch (cause) {
      if (cause instanceof MeterRefusal) return this.unavailable(locale, cause.code, null, null);
      throw cause;
    }
    if (open.config.promptVersion !== PROMPT_VERSION) {
      return this.unavailable(locale, "prompt_version_mismatch", open, null);
    }

    const state: FlowState = {
      turns: [
        ...(input.history ?? [])
          .slice(-MAX_HISTORY_TURNS)
          .map((turn): Turn =>
            turn.role === "user"
              ? { role: "user", text: turn.text.slice(0, MAX_QUESTION_CHARS) }
              : { role: "model", text: turn.text.slice(0, 4 * MAX_QUESTION_CHARS), toolCalls: [] },
          ),
        { role: "user", text: question },
      ],
      results: [],
      records: [],
      modelCalls: 0,
      toolCalls: 0,
    };
    const tools = this.deps.registry.available(caller).map(toolSpec);
    const system = systemPrompt(locale);

    try {
      let reply = await this.toolLoop(open, state, system, tools, caller, idToken);
      let check = this.check(reply.text, state.results);
      const firstPassVerified = check.verified;
      if (!check.verified) {
        state.turns.push({ role: "model", text: reply.text, toolCalls: [] });
        state.turns.push({ role: "user", text: verifierRetry(check.unsupported) });
        reply = await this.generate(open, state, system, []);
        check = this.check(reply.text, state.results);
      }
      return this.finish(locale, open, state, {
        status: check.verified ? "answered" : "unverified",
        answerMd: check.verified ? check.markdown : FALLBACK_NOTE[locale],
        productIds: check.verified ? check.productIds : [],
        firstPassVerified,
      });
    } catch (cause) {
      if (cause instanceof MeterRefusal || cause instanceof FlowError) {
        const code = cause instanceof MeterRefusal ? cause.code : cause.code;
        // Tool results already fetched are still shown, with the fallback note.
        if (state.results.length > 0) {
          return this.finish(locale, open, state, {
            status: "unverified",
            code,
            answerMd: FALLBACK_NOTE[locale],
            productIds: [],
            firstPassVerified: false,
          });
        }
        return this.unavailable(locale, code, open, state);
      }
      throw cause;
    }
  }

  private async toolLoop(
    question: Question,
    state: FlowState,
    system: string,
    tools: readonly ToolSpec[],
    caller: CallerContext,
    idToken: string,
  ): Promise<ModelReply> {
    const maxToolCalls = this.deps.maxToolCalls ?? MAX_TOOL_CALLS;
    for (;;) {
      const budgetLeft = state.toolCalls < maxToolCalls;
      const reply = await this.generate(question, state, system, budgetLeft ? tools : []);
      if (reply.toolCalls.length === 0) return reply;
      state.turns.push({ role: "model", text: reply.text, toolCalls: reply.toolCalls });
      const results: { call: (typeof reply.toolCalls)[number]; output: unknown }[] = [];
      for (const call of reply.toolCalls) {
        if (state.toolCalls >= maxToolCalls) {
          results.push({ call, output: { status: "error", message: TOOL_BUDGET_SPENT } });
          continue;
        }
        state.toolCalls += 1;
        const result = await this.deps.registry.run(call.name, call.args, caller, idToken);
        state.records.push({
          name: call.name,
          args: call.args,
          status: result.status,
          ...(result.status === "error" ? { code: result.code } : {}),
        });
        if (result.status !== "error") state.results.push(result);
        results.push({ call, output: result });
      }
      state.turns.push({ role: "tool", results });
    }
  }

  private async generate(
    question: Question,
    state: FlowState,
    system: string,
    tools: readonly ToolSpec[],
  ): Promise<ModelReply> {
    const limits = limitsOf(question.config);
    const base = { system, turns: [...state.turns], tools };
    // Checked before reserving: a call that cannot fit is never made or charged.
    if (promptTokenBound(base) > limits.maxInputTokens) throw new FlowError("prompt_too_large");
    return this.deps.meter.call(question, async (callLimits, model) => {
      state.modelCalls += 1;
      const request: ModelRequest = {
        ...base,
        model,
        limits: callLimits,
        temperature: TEMPERATURE,
      };
      let reply: ModelReply;
      try {
        reply = await this.deps.model.generate(request);
      } catch {
        throw new FlowError("model_error");
      }
      return { usage: reply.usage, value: reply };
    });
  }

  private check(text: string, results: readonly ToolEnvelope[]) {
    const cleaned = cleanAnswer(text, knownProductIds(results));
    const verdict = verifyAnswerNumbers(cleaned.markdown, results);
    return {
      verified: verdict.ok && cleaned.markdown.length > 0,
      unsupported: verdict.unsupported,
      markdown: cleaned.markdown,
      productIds: cleaned.productIds,
    };
  }

  private finish(
    locale: Locale,
    question: Question,
    state: FlowState,
    outcome: {
      status: AnswerStatus;
      code?: RefusalCode | FlowCode;
      answerMd: string;
      productIds: readonly string[];
      firstPassVerified: boolean;
    },
  ): ChatAnswer {
    return {
      ...outcome,
      language: locale,
      promptVersion: PROMPT_VERSION,
      model: question.config.model,
      citations: state.results.map((result) => result.citation),
      caveats: state.results.flatMap((result) => result.caveats),
      notEnoughData: state.results.flatMap((result) =>
        result.notEnoughData ? [{ tool: result.citation.tool, ...result.notEnoughData }] : [],
      ),
      toolCalls: state.records,
      toolResults: outcome.status === "answered" ? [] : state.results,
      modelCalls: state.modelCalls,
      costUsd: formatUsd(question.spent),
    };
  }

  private unavailable(
    locale: Locale,
    code: RefusalCode | FlowCode,
    question: Question | null,
    state: FlowState | null,
  ): ChatAnswer {
    return {
      status: "unavailable",
      code,
      answerMd: UNAVAILABLE_NOTE[locale],
      language: locale,
      promptVersion: PROMPT_VERSION,
      model: question?.config.model ?? null,
      firstPassVerified: false,
      citations: [],
      caveats: [],
      productIds: [],
      notEnoughData: [],
      toolCalls: state?.records ?? [],
      toolResults: [],
      modelCalls: state?.modelCalls ?? 0,
      costUsd: formatUsd(question?.spent ?? 0n),
    };
  }
}

export class FlowError extends Error {
  constructor(readonly code: FlowCode) {
    super(`chat flow: ${code}`);
    this.name = "FlowError";
  }
}
