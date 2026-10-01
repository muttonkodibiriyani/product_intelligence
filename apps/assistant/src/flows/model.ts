/**
 * The model boundary. The chat flow drives the tool loop itself, so every model call passes the
 * meter and every tool call passes the registry with the user's token. The model only ever
 * proposes tool calls or answer text; it executes nothing.
 */
import type { CallLimits, TokenUsage } from "../meter/prices.js";

export interface ToolSpec {
  readonly name: string;
  readonly description: string;
  /** JSON Schema for the arguments (generated from the tool's zod input). */
  readonly parameters: unknown;
}

export interface ToolCall {
  /** Provider call id, echoed back with the result when the provider sets one. */
  readonly id?: string;
  readonly name: string;
  readonly args: unknown;
}

export type Turn =
  | { readonly role: "user"; readonly text: string }
  | { readonly role: "model"; readonly text: string; readonly toolCalls: readonly ToolCall[] }
  | {
      readonly role: "tool";
      readonly results: readonly { readonly call: ToolCall; readonly output: unknown }[];
    };

export interface ModelRequest {
  readonly model: string;
  readonly system: string;
  readonly turns: readonly Turn[];
  /** Empty when the model must answer without further tool calls. */
  readonly tools: readonly ToolSpec[];
  readonly limits: CallLimits;
  readonly temperature: number;
}

export interface ModelReply {
  readonly text: string;
  readonly toolCalls: readonly ToolCall[];
  readonly usage: TokenUsage;
}

export interface ChatModel {
  generate(request: ModelRequest): Promise<ModelReply>;
}

/** Tokens the provider adds around our text (roles, function-declaration framing). */
export const FRAMING_TOKENS = 1_000;

/**
 * Bound on prompt tokens without a token-count call: every text token is at least one UTF-8
 * byte, so the serialised request's byte length plus a framing margin bounds the prompt. The
 * flow refuses a call whose bound exceeds `maxInputTokens`, which keeps calls inside the
 * meter's reserved ceiling. If a provider ever bills more, the meter still counts it in full.
 */
export function promptTokenBound(
  request: Pick<ModelRequest, "system" | "turns" | "tools">,
): number {
  const text = JSON.stringify([request.system, request.turns, request.tools]);
  return Buffer.byteLength(text, "utf8") + FRAMING_TOKENS;
}
