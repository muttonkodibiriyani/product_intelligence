/**
 * Gemini on Vertex AI through the official `@google/genai` SDK (decision 2026-10-01: replaces
 * Genkit, whose telemetry dependencies carried high-severity advisories).
 *
 * Vertex mode with Application Default Credentials only: the runtime service account in
 * production, a CI identity through Workload Identity Federation in evals. There is no API-key
 * path. `create` refuses to start if any environment variable could switch the SDK to an API
 * key, inject a token, or redirect its traffic, and it accepts only the allowed project.
 */
import {
  type Content,
  type GenerateContentParameters,
  type GenerateContentResponse,
  GoogleGenAI,
  type Part,
} from "@google/genai";

import type { TokenUsage } from "../meter/prices.js";
import type { ChatModel, ModelReply, ModelRequest, ToolCall, Turn } from "./model.js";

/** The only Firebase/GCP project this code may call (operator rule). */
export const ALLOWED_PROJECT = "productintelligence-beeb3";

/** Environment variables that must be unset: API keys, token injection, endpoint overrides. */
export const FORBIDDEN_ENV = [
  "GEMINI_API_KEY",
  "GOOGLE_API_KEY",
  "GOOGLE_GENAI_API_KEY",
  "GOOGLE_GENAI_ACCESS_TOKEN",
  "GOOGLE_GEMINI_BASE_URL",
  "GOOGLE_VERTEX_BASE_URL",
] as const;

export interface GenerateContentClient {
  generateContent(params: GenerateContentParameters): Promise<GenerateContentResponse>;
}

export class VertexConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VertexConfigError";
  }
}

export function checkVertexEnvironment(
  options: { project: string; location: string },
  env: Readonly<Record<string, string | undefined>>,
): void {
  const set = FORBIDDEN_ENV.filter((name) => (env[name] ?? "") !== "");
  if (set.length > 0) {
    throw new VertexConfigError(`refusing to start: unset ${set.join(", ")} (Vertex ADC only)`);
  }
  if (options.project !== ALLOWED_PROJECT) {
    throw new VertexConfigError(`refusing to start: project must be ${ALLOWED_PROJECT}`);
  }
  if (!/^[a-z]+(?:-[a-z]+)*\d*$/.test(options.location)) {
    throw new VertexConfigError("refusing to start: invalid location");
  }
}

function contents(turns: readonly Turn[]): Content[] {
  return turns.map((turn): Content => {
    switch (turn.role) {
      case "user":
        return { role: "user", parts: [{ text: turn.text }] };
      case "model":
        return {
          role: "model",
          parts: [
            ...(turn.text === "" ? [] : [{ text: turn.text }]),
            ...turn.toolCalls.map((call): Part => ({
              functionCall: {
                ...(call.id === undefined ? {} : { id: call.id }),
                name: call.name,
                args: isRecord(call.args) ? call.args : {},
              },
            })),
          ],
        };
      case "tool":
        return {
          role: "user",
          parts: turn.results.map(({ call, output }): Part => ({
            functionResponse: {
              ...(call.id === undefined ? {} : { id: call.id }),
              name: call.name,
              response: { output },
            },
          })),
        };
    }
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Missing counts become NaN, which the meter's price table rejects, so it charges the ceiling. */
function usageOf(response: GenerateContentResponse): TokenUsage {
  const meta = response.usageMetadata;
  const count = (value: number | undefined) => value ?? Number.NaN;
  if (meta === undefined) {
    return { input: Number.NaN, cachedInput: 0, output: Number.NaN, thinking: 0 };
  }
  return {
    input: count(meta.promptTokenCount) + (meta.toolUsePromptTokenCount ?? 0),
    cachedInput: meta.cachedContentTokenCount ?? 0,
    output: count(meta.candidatesTokenCount),
    thinking: meta.thoughtsTokenCount ?? 0,
  };
}

export function buildRequest(request: ModelRequest): GenerateContentParameters {
  return {
    model: request.model,
    contents: contents(request.turns),
    config: {
      systemInstruction: request.system,
      temperature: request.temperature,
      maxOutputTokens: request.limits.maxOutputTokens,
      thinkingConfig: { thinkingBudget: request.limits.thinkingBudget },
      candidateCount: 1,
      ...(request.tools.length === 0
        ? {}
        : {
            tools: [
              {
                functionDeclarations: request.tools.map((tool) => ({
                  name: tool.name,
                  description: tool.description,
                  parametersJsonSchema: tool.parameters,
                })),
              },
            ],
          }),
      automaticFunctionCalling: { disable: true },
    },
  };
}

export function parseReply(response: GenerateContentResponse): ModelReply {
  const parts = response.candidates?.[0]?.content?.parts ?? [];
  const text = parts
    .filter((part) => part.thought !== true && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
  const toolCalls = parts.flatMap((part): ToolCall[] => {
    const call = part.functionCall;
    if (call === undefined) return [];
    return [
      {
        ...(call.id === undefined ? {} : { id: call.id }),
        name: call.name ?? "",
        args: call.args ?? {},
      },
    ];
  });
  return { text, toolCalls, usage: usageOf(response) };
}

export class VertexChatModel implements ChatModel {
  constructor(private readonly client: GenerateContentClient) {}

  static create(
    options: { project: string; location: string },
    env: Readonly<Record<string, string | undefined>> = process.env,
  ): VertexChatModel {
    checkVertexEnvironment(options, env);
    const ai = new GoogleGenAI({
      vertexai: true,
      project: options.project,
      location: options.location,
    });
    return new VertexChatModel(ai.models);
  }

  async generate(request: ModelRequest): Promise<ModelReply> {
    return parseReply(await this.client.generateContent(buildRequest(request)));
  }
}
