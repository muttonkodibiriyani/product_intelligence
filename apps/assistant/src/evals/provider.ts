/**
 * promptfoo provider for the assistant suites (design §8). Each test case runs the real
 * `ChatFlow`, with tools answering from `FixtureApi`, metered under the "ci" label.
 *
 * Real model calls go to Vertex and are metered against the shared Firestore counters only:
 * the provider refuses to start unless `PI_EVAL_METER=firestore`, so the ci cap and the live
 * month cap apply across runs. There is no in-memory mode for real calls. `PI_VERTEX_LOCATION`
 * must be set explicitly; ADC supplies credentials. `PI_EVAL_MODEL` picks a candidate from the
 * committed `evals/eval-config.json`, and the meter runs on that file bounded by
 * `assistant_config/current` (`eval-config.ts`); the live switch and model are never changed.
 *
 * Each case gets its own synthetic uid (`ci-<role>-<run>-<n>`): the per-user daily question cap
 * is for people; CI spend is bounded by the ci label cap.
 */
import { randomUUID } from "node:crypto";

import { type ChatAnswer, ChatFlow } from "../flows/chat.js";
import { NO_THREADS } from "../flows/threads.js";
import type { ChatModel } from "../flows/model.js";
import type { Locale } from "../flows/prompt.js";
import { ALLOWED_PROJECT, VertexChatModel } from "../flows/vertex.js";
import { type ConfigSource, Meter, type UsageStore } from "../meter/meter.js";
import { type Prices, loadPrices } from "../meter/prices.js";
import { TOOLS } from "../tools/definitions.js";
import { ToolRegistry } from "../tools/registry.js";
import type { Role } from "../tools/types.js";
import { EVAL_LABEL, evalConfigSource, loadEvalConfig } from "./eval-config.js";
import { FixtureApi, SCENARIOS, type Scenario } from "./fixtures.js";

export { loadPrices };

export { EVAL_LABEL };
export const EVIDENCE_HOSTS = ["shop.north.example", "south.example"];

export interface EvalDeps {
  readonly model: ChatModel;
  readonly store: UsageStore;
  readonly prices: Prices;
  /** The meter's config source: always the eval source for real calls. */
  readonly source: ConfigSource;
}

/** The subset of promptfoo's provider response this provider fills. */
export interface EvalResponse {
  readonly output?: ChatAnswer;
  readonly error?: string;
  readonly cost?: number;
  readonly metadata?: { readonly apiCalls: number; readonly scenario: Scenario };
}

export class EvalConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvalConfigError";
  }
}

/** Production dependencies: Vertex (ADC) plus the shared Firestore meter. */
export async function vertexDeps(
  env: Readonly<Record<string, string | undefined>> = process.env,
): Promise<EvalDeps> {
  if (env.PI_EVAL_METER !== "firestore") {
    throw new EvalConfigError(
      "evals call Vertex: set PI_EVAL_METER=firestore so the shared ci cap and kill switch apply",
    );
  }
  const location = env.PI_VERTEX_LOCATION ?? "";
  if (location === "") throw new EvalConfigError("set PI_VERTEX_LOCATION");
  const evalModel = env.PI_EVAL_MODEL ?? "";
  // Fails fast; the meter refuses an unset or unlisted model on every call anyway.
  if (evalModel === "")
    throw new EvalConfigError("set PI_EVAL_MODEL to a model in evals/eval-config.json");
  // Refuses API keys, token injection, endpoint overrides and any other project.
  const model = VertexChatModel.create({ project: ALLOWED_PROJECT, location }, env);
  const { initializeApp } = await import("firebase-admin/app");
  const { getFirestore } = await import("firebase-admin/firestore");
  const { FirestoreUsageStore } = await import("../meter/firestore-store.js");
  const app = initializeApp({ projectId: ALLOWED_PROJECT }, `assistant-evals-${randomUUID()}`);
  return {
    model,
    store: new FirestoreUsageStore(getFirestore(app)),
    prices: loadPrices(),
    source: evalConfigSource(loadEvalConfig(), evalModel),
  };
}

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  if (value === undefined) return fallback;
  if (typeof value === "string" && (allowed as readonly string[]).includes(value)) {
    return value as T;
  }
  throw new EvalConfigError(`unexpected test variable: ${JSON.stringify(value)}`);
}

export default class AssistantEvalProvider {
  private deps: Promise<EvalDeps> | undefined;
  private readonly run = randomUUID().slice(0, 8);
  private seq = 0;

  constructor(
    private readonly options: { readonly id?: string } = {},
    private readonly makeDeps: () => Promise<EvalDeps> = () => vertexDeps(),
  ) {}

  id(): string {
    return this.options.id ?? "pi-assistant";
  }

  async callApi(
    prompt: string,
    context?: { readonly vars?: Readonly<Record<string, unknown>> },
  ): Promise<EvalResponse> {
    const vars = context?.vars ?? {};
    let scenario: Scenario;
    let role: Role;
    let locale: Locale;
    try {
      scenario = pick(vars.scenario, SCENARIOS, "standard");
      role = pick<Role>(vars.role, ["viewer", "admin"], "viewer");
      locale = pick<Locale>(vars.locale, ["en", "ar"], "en");
    } catch (cause) {
      return { error: String(cause) };
    }
    this.deps ??= this.makeDeps();
    const deps = await this.deps;
    const api = new FixtureApi(scenario);
    const flow = new ChatFlow({
      meter: new Meter(deps.store, deps.prices, undefined, undefined, deps.source),
      model: deps.model,
      registry: new ToolRegistry(TOOLS, api, { evidenceHosts: EVIDENCE_HOSTS }),
      // Every eval case is a fresh question with no thread.
      threads: NO_THREADS,
      label: EVAL_LABEL,
    });
    this.seq += 1;
    const caller = { uid: `ci-${role}-${this.run}-${String(this.seq)}`, role };
    const answer = await flow.answer({ question: prompt, locale }, caller, "eval-token");
    return {
      output: answer,
      cost: Number(answer.costUsd),
      metadata: { apiCalls: api.calls.length, scenario },
    };
  }
}
