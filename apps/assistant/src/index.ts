/**
 * Cloud Functions entry point (codebase `assistant`, `apps/assistant/firebase.json`). Only
 * adapters live here; the logic is in `src/functions/` and is tested without the runtime.
 * Deploying is an owner step that needs an explicit OK (design §9.4, §10.1).
 */
import { logger } from "firebase-functions";
import { defineSecret } from "firebase-functions/params";
import { HttpsError, onCall } from "firebase-functions/v2/https";
import { onMessagePublished } from "firebase-functions/v2/pubsub";

import { CallableRefusal, handleChat } from "./functions/callable.js";
import { ENV } from "./functions/env.js";
import { checkStartupEnv, createChatFlow, killSwitchDeps } from "./functions/runtime.js";
import type { ChatFlow } from "./flows/chat.js";
import { handleBudgetMessage } from "./killswitch/handler.js";

const REGION = "me-central1";

/** Secret Manager secret holding the kill-switch account's password (§9.4 step 3). */
const killSwitchPassword = defineSecret(ENV.password);

checkStartupEnv(process.env);

const log = (entry: Readonly<Record<string, unknown>>): void => {
  logger.write({ ...entry, message: String(entry.event) } as Parameters<typeof logger.write>[0]);
};

/** Budget alert → switch the assistant off (§9.4). A throw means "retry"; age bounds retries. */
export const budgetKillSwitch = onMessagePublished(
  {
    topic: "pi-budget-alerts",
    region: REGION,
    retry: true,
    serviceAccount: "pi-killswitch@",
    secrets: [killSwitchPassword],
    minInstances: 0,
    maxInstances: 1,
    memory: "256MiB",
    timeoutSeconds: 60,
  },
  async (event) => {
    await handleBudgetMessage(event.data.message, killSwitchDeps(process.env, log));
  },
);

let flow: Promise<ChatFlow> | undefined;

/** The chat callable (§3, §6). Role is checked in `handleChat` before the meter runs. */
export const assistantChat = onCall(
  {
    region: REGION,
    enforceAppCheck: true,
    serviceAccount: "pi-assistant@",
    minInstances: 0,
    maxInstances: 5,
    memory: "512MiB",
    timeoutSeconds: 120,
  },
  async (request) => {
    try {
      return await handleChat(request, {
        answer: async (...args) => (await (flow ??= createChatFlow(process.env))).answer(...args),
      });
    } catch (cause) {
      if (cause instanceof CallableRefusal) throw new HttpsError(cause.code, cause.message);
      throw cause;
    }
  },
);
