/**
 * Deploy configuration for the Cloud Functions in `src/index.ts` (design §9.4 step 4). Every
 * value comes from the environment (Functions params and one secret); nothing is a literal in
 * `src/`. A missing or malformed value refuses to start (reviewer D1): the kill switch must never
 * run with a guessed currency or an empty budget id, because either would make it ignore every
 * real alert.
 */
import type { KillSwitchPolicy } from "../killswitch/budget.js";
import type { KillSwitchAccount, KillSwitchTarget } from "../killswitch/switch.js";
import { ALLOWED_PROJECT } from "../flows/vertex.js";

type Env = Readonly<Record<string, string | undefined>>;

/** Switch off at 90 % of the budget; alerts older than 6 h are acked without action (§9.4). */
export const THRESHOLD_PCT = 90;
export const MAX_ALERT_AGE_MS = 6 * 3600_000;

/**
 * Variable names. The values come from the gitignored `.env.productintelligence-beeb3` (see
 * `.env.example`); only the password is a declared secret (`defineSecret` in `src/index.ts`).
 */
export const ENV = {
  budgetId: "KILL_SWITCH_BUDGET_ID",
  currency: "KILL_SWITCH_CURRENCY",
  apiKey: "KILL_SWITCH_API_KEY",
  email: "KILL_SWITCH_EMAIL",
  password: "KILL_SWITCH_PASSWORD",
  apiBaseUrl: "PI_API_BASE_URL",
  vertexLocation: "PI_VERTEX_LOCATION",
  evidenceHosts: "PI_EVIDENCE_HOSTS",
} as const;

export class DeployConfigError extends Error {
  constructor(message: string) {
    super(`refusing to start: ${message}`);
    this.name = "DeployConfigError";
  }
}

export interface KillSwitchEnv {
  readonly policy: KillSwitchPolicy;
  readonly target: KillSwitchTarget;
  readonly account: KillSwitchAccount;
}

export interface ChatEnv {
  readonly apiBaseUrl: string;
  readonly vertexLocation: string;
  readonly evidenceHosts: readonly string[];
}

/** The project the runtime reports; anything but the one allowed project refuses. */
export function deployProject(env: Env): string {
  const project = env.GCLOUD_PROJECT ?? env.GOOGLE_CLOUD_PROJECT ?? "";
  if (project !== ALLOWED_PROJECT) {
    throw new DeployConfigError(`project must be ${ALLOWED_PROJECT}`);
  }
  return project;
}

/**
 * Values are checked for shape only and never echoed: an error names the variable, not its
 * content, so a mis-set secret cannot reach the log.
 */
function required(env: Env, name: string, pattern: RegExp): string {
  const value = env[name] ?? "";
  if (!pattern.test(value)) throw new DeployConfigError(`${name} is missing or invalid`);
  return value;
}

export function loadKillSwitchEnv(env: Env): KillSwitchEnv {
  const projectId = deployProject(env);
  return {
    policy: {
      // Billing budget ids are UUIDs; anything else (including empty) cannot match an alert.
      budgetId: required(env, ENV.budgetId, /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/),
      // ISO 4217 code, as the owner records it at step 1. Never defaulted.
      currency: required(env, ENV.currency, /^[A-Z]{3}$/),
      thresholdPct: THRESHOLD_PCT,
      maxAgeMs: MAX_ALERT_AGE_MS,
    },
    target: { projectId, apiKey: required(env, ENV.apiKey, /^[A-Za-z0-9_-]{20,100}$/) },
    account: {
      email: required(env, ENV.email, /^[^\s@]+@[^\s@]+\.[^\s@]+$/),
      password: required(env, ENV.password, /^\S{12,}$/),
    },
  };
}

const HOST = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

export function loadChatEnv(env: Env): ChatEnv {
  deployProject(env);
  const apiBaseUrl = required(env, ENV.apiBaseUrl, /^https:\/\/[^\s/?#]+(?:\/[^\s?#]*)?$/);
  // The tools add /api/v1 themselves. A base that already ends in it doubled the path and every
  // tool got a 404 (2026-10-03); the client now tolerates it, but the deploy setting is wrong.
  if (/\/api\/v1\/*$/i.test(new URL(apiBaseUrl).pathname)) {
    throw new DeployConfigError(`${ENV.apiBaseUrl} must not end in /api/v1 (the tools add it)`);
  }
  const vertexLocation = required(env, ENV.vertexLocation, /^[a-z]+(?:-[a-z]+)*\d*$/);
  // Exact hosts, comma-separated (no wildcards, schemes or paths); same list as pi_api's.
  const evidenceHosts = required(env, ENV.evidenceHosts, /^\S+$/).split(",");
  if (!evidenceHosts.every((host) => HOST.test(host))) {
    throw new DeployConfigError(`${ENV.evidenceHosts} is missing or invalid`);
  }
  return { apiBaseUrl, vertexLocation, evidenceHosts };
}
