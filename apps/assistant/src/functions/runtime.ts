/**
 * Builds each function's dependencies from the environment. Kept apart from `src/index.ts` so
 * the composition and the startup check are tested without the Functions runtime.
 */
import type { KillSwitchDeps } from "../killswitch/handler.js";
import { RulesScopedSwitch } from "../killswitch/switch.js";
import { loadChatEnv, loadKillSwitchEnv } from "./env.js";
import type { ChatFlow } from "../flows/chat.js";

type Env = Readonly<Record<string, string | undefined>>;

/** Exported names in `src/index.ts`; Cloud Functions sets `FUNCTION_TARGET` to one of them. */
export const FUNCTIONS = { killSwitch: "budgetKillSwitch", chat: "assistantChat" } as const;

/**
 * Container start (reviewer D1): refuse to start with a missing or malformed setting, so a bad
 * deploy fails its revision instead of acking alerts it cannot act on. Each function checks only
 * its own settings, so the kill switch deploys without the chat's. An unknown target checks
 * both. Skipped while the Firebase CLI loads the code to discover the functions.
 */
export function checkStartupEnv(env: Env): void {
  if (env.FUNCTIONS_CONTROL_API === "true") return;
  const target = env.FUNCTION_TARGET;
  if (target !== FUNCTIONS.chat) loadKillSwitchEnv(env);
  if (target !== FUNCTIONS.killSwitch) loadChatEnv(env);
}

export function killSwitchDeps(
  env: Env,
  log: KillSwitchDeps["log"],
  doFetch: typeof fetch = fetch,
): KillSwitchDeps {
  const { policy, target, account } = loadKillSwitchEnv(env);
  return { policy, configSwitch: new RulesScopedSwitch(target, account, doFetch), log };
}

/** The production chat flow: Vertex (ADC), the Firestore meter and threads, the service layer. */
export async function createChatFlow(env: Env): Promise<ChatFlow> {
  const config = loadChatEnv(env);
  const { ALLOWED_PROJECT, VertexChatModel } = await import("../flows/vertex.js");
  // Refuses API keys, token injection, endpoint overrides and any other project.
  const model = VertexChatModel.create(
    { project: ALLOWED_PROJECT, location: config.vertexLocation },
    env,
  );
  const [{ getApps, initializeApp }, { getFirestore }] = await Promise.all([
    import("firebase-admin/app"),
    import("firebase-admin/firestore"),
  ]);
  const { ChatFlow } = await import("../flows/chat.js");
  const { FirestoreThreadStore } = await import("../flows/threads.js");
  const { FirestoreUsageStore } = await import("../meter/firestore-store.js");
  const { Meter } = await import("../meter/meter.js");
  const { loadPrices } = await import("../meter/prices.js");
  const { HttpMetricApi } = await import("../api/client.js");
  const { TOOLS } = await import("../tools/definitions.js");
  const { ToolRegistry } = await import("../tools/registry.js");
  const app = getApps()[0] ?? initializeApp({ projectId: ALLOWED_PROJECT });
  const db = getFirestore(app);
  return new ChatFlow({
    meter: new Meter(new FirestoreUsageStore(db), loadPrices()),
    model,
    registry: new ToolRegistry(TOOLS, new HttpMetricApi(config.apiBaseUrl), {
      evidenceHosts: config.evidenceHosts,
    }),
    threads: new FirestoreThreadStore(db),
  });
}
