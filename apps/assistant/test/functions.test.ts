import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatFlow } from "../src/flows/chat.js";
import type { ChatModel } from "../src/flows/model.js";
import { PROMPT_VERSION } from "../src/flows/prompt.js";
import { MemoryThreadStore } from "../src/flows/threads.js";
import { CallableRefusal, callerFrom, handleChat } from "../src/functions/callable.js";
import {
  DeployConfigError,
  MAX_ALERT_AGE_MS,
  THRESHOLD_PCT,
  loadChatEnv,
  loadKillSwitchEnv,
} from "../src/functions/env.js";
import {
  FUNCTIONS,
  checkStartupEnv,
  createChatFlow,
  killSwitchDeps,
} from "../src/functions/runtime.js";
import { handleBudgetMessage } from "../src/killswitch/handler.js";
import { MemoryUsageStore } from "../src/meter/memory-store.js";
import { Meter } from "../src/meter/meter.js";
import { TOOLS } from "../src/tools/definitions.js";
import { ToolRegistry } from "../src/tools/registry.js";
import type { CallerContext } from "../src/tools/types.js";
import { FakeApi, okEnvelope } from "./fake-api.js";
import { CONFIG, prices } from "./meter-fixtures.js";

const BUDGET_ID = "0d2c8a54-6f1e-4b7a-9c3d-2e5f8a1b7c90";
const KILL_SWITCH_ENV = {
  GCLOUD_PROJECT: "productintelligence-beeb3",
  KILL_SWITCH_BUDGET_ID: BUDGET_ID,
  KILL_SWITCH_CURRENCY: "AED",
  KILL_SWITCH_API_KEY: "AIzaSyFakeKeyForTests_0123456789",
  KILL_SWITCH_EMAIL: "ks+switch@example.test",
  KILL_SWITCH_PASSWORD: "correct-horse-battery",
};
const CHAT_ENV = {
  GCLOUD_PROJECT: "productintelligence-beeb3",
  PI_API_BASE_URL: "https://pi.example.test",
  PI_VERTEX_LOCATION: "europe-west4",
  PI_EVIDENCE_HOSTS: "www.sephora.me",
};

function refusal(load: () => unknown): DeployConfigError {
  try {
    load();
  } catch (caught) {
    expect(caught).toBeInstanceOf(DeployConfigError);
    return caught as DeployConfigError;
  }
  throw new Error("expected a DeployConfigError");
}

describe("loadKillSwitchEnv (reviewer D1)", () => {
  it("builds the policy, target and account from the environment", () => {
    expect(loadKillSwitchEnv(KILL_SWITCH_ENV)).toEqual({
      policy: {
        budgetId: BUDGET_ID,
        currency: "AED",
        thresholdPct: THRESHOLD_PCT,
        maxAgeMs: MAX_ALERT_AGE_MS,
      },
      target: {
        projectId: "productintelligence-beeb3",
        apiKey: KILL_SWITCH_ENV.KILL_SWITCH_API_KEY,
      },
      account: { email: "ks+switch@example.test", password: "correct-horse-battery" },
    });
    expect(THRESHOLD_PCT).toBe(90);
    expect(MAX_ALERT_AGE_MS).toBe(6 * 3600_000);
  });

  it.each([
    ["KILL_SWITCH_CURRENCY", undefined],
    ["KILL_SWITCH_CURRENCY", ""],
    ["KILL_SWITCH_CURRENCY", "usd"],
    ["KILL_SWITCH_CURRENCY", "US"],
    ["KILL_SWITCH_CURRENCY", "USD "],
    ["KILL_SWITCH_CURRENCY", "US$"],
    ["KILL_SWITCH_BUDGET_ID", undefined],
    ["KILL_SWITCH_BUDGET_ID", ""],
    ["KILL_SWITCH_BUDGET_ID", "pi-monthly-25usd"],
    ["KILL_SWITCH_BUDGET_ID", `${BUDGET_ID}\n`],
    ["KILL_SWITCH_API_KEY", ""],
    ["KILL_SWITCH_EMAIL", "not-an-email"],
    ["KILL_SWITCH_PASSWORD", undefined],
    ["KILL_SWITCH_PASSWORD", "short"],
  ])("refuses to start when %s is %j, naming the variable only", (name, value) => {
    const error = refusal(() => loadKillSwitchEnv({ ...KILL_SWITCH_ENV, [name]: value }));
    expect(error.message).toBe(`refusing to start: ${name} is missing or invalid`);
  });

  it.each([undefined, "", "demo-pi", "other-project"])(
    "refuses any project but productintelligence-beeb3 (%j)",
    (project) => {
      const env = { ...KILL_SWITCH_ENV, GCLOUD_PROJECT: project };
      expect(refusal(() => loadKillSwitchEnv(env)).message).toContain("project must be");
    },
  );

  it("accepts GOOGLE_CLOUD_PROJECT when GCLOUD_PROJECT is unset", () => {
    const env = {
      ...KILL_SWITCH_ENV,
      GCLOUD_PROJECT: undefined,
      GOOGLE_CLOUD_PROJECT: "productintelligence-beeb3",
    };
    expect(loadKillSwitchEnv(env).target.projectId).toBe("productintelligence-beeb3");
  });

  it("never echoes a value, even a mis-set password", () => {
    const env = { ...KILL_SWITCH_ENV, KILL_SWITCH_PASSWORD: "has a space in it" };
    expect(refusal(() => loadKillSwitchEnv(env)).message).not.toContain("space");
  });
});

describe("loadChatEnv", () => {
  it("reads the service URL, Vertex location and exact evidence hosts", () => {
    expect(loadChatEnv({ ...CHAT_ENV, PI_EVIDENCE_HOSTS: "www.sephora.me,shop.example" })).toEqual({
      apiBaseUrl: "https://pi.example.test",
      vertexLocation: "europe-west4",
      evidenceHosts: ["www.sephora.me", "shop.example"],
    });
  });

  it.each([
    ["PI_API_BASE_URL", "http://pi.example.test"],
    ["PI_API_BASE_URL", "https://pi.example.test?x=1"],
    ["PI_API_BASE_URL", undefined],
    ["PI_VERTEX_LOCATION", "Europe West"],
    ["PI_EVIDENCE_HOSTS", ""],
    ["PI_EVIDENCE_HOSTS", "*.sephora.me"],
    ["PI_EVIDENCE_HOSTS", "https://www.sephora.me"],
    ["PI_EVIDENCE_HOSTS", "www.sephora.me,"],
    ["PI_EVIDENCE_HOSTS", "WWW.SEPHORA.ME"],
  ])("refuses %s=%j", (name, value) => {
    const error = refusal(() => loadChatEnv({ ...CHAT_ENV, [name]: value }));
    expect(error.message).toBe(`refusing to start: ${name} is missing or invalid`);
  });

  it("refuses another project", () => {
    expect(() => loadChatEnv({ ...CHAT_ENV, GCLOUD_PROJECT: "x" })).toThrow(DeployConfigError);
  });
});

describe("checkStartupEnv", () => {
  it("checks only the target function's settings", () => {
    const killSwitch = { ...KILL_SWITCH_ENV, FUNCTION_TARGET: FUNCTIONS.killSwitch };
    expect(() => {
      checkStartupEnv(killSwitch);
    }).not.toThrow();
    expect(() => {
      checkStartupEnv({ ...killSwitch, KILL_SWITCH_CURRENCY: undefined });
    }).toThrow("KILL_SWITCH_CURRENCY");
    const chat = { ...CHAT_ENV, FUNCTION_TARGET: FUNCTIONS.chat };
    expect(() => {
      checkStartupEnv(chat);
    }).not.toThrow();
    expect(() => {
      checkStartupEnv({ ...chat, PI_API_BASE_URL: undefined });
    }).toThrow("PI_API_BASE_URL");
  });

  it("checks both for an unknown or missing target", () => {
    expect(() => {
      checkStartupEnv(KILL_SWITCH_ENV);
    }).toThrow("PI_API_BASE_URL");
    expect(() => {
      checkStartupEnv({ ...CHAT_ENV, FUNCTION_TARGET: "other" });
    }).toThrow("KILL_SWITCH_BUDGET_ID");
    expect(() => {
      checkStartupEnv({ ...KILL_SWITCH_ENV, ...CHAT_ENV });
    }).not.toThrow();
  });

  it("is skipped while the Firebase CLI discovers the functions", () => {
    expect(() => {
      checkStartupEnv({ FUNCTIONS_CONTROL_API: "true" });
    }).not.toThrow();
  });
});

describe("killSwitchDeps", () => {
  it("wires the env into a rules-scoped switch that acts on a matching alert", async () => {
    const urls: string[] = [];
    const doFetch = ((url: string) => {
      urls.push(url);
      const body = urls.length === 1 ? { idToken: "id-1" } : {};
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    }) as unknown as typeof fetch;
    const logs: Readonly<Record<string, unknown>>[] = [];
    const deps = killSwitchDeps(KILL_SWITCH_ENV, (entry) => logs.push(entry), doFetch);
    const now = new Date();
    const data = {
      costAmount: 90,
      budgetAmount: 100,
      currencyCode: "AED",
      costIntervalStart: `${now.toISOString().slice(0, 7)}-01T00:00:00Z`,
      budgetAmountType: "SPECIFIED_AMOUNT",
      alertThresholdExceeded: 0.9,
      budgetDisplayName: "pi-monthly-25usd",
    };
    const message = {
      data: Buffer.from(JSON.stringify(data)).toString("base64"),
      attributes: { budgetId: BUDGET_ID, schemaVersion: "1.0" },
      publishTime: now.toISOString(),
    };
    await expect(handleBudgetMessage(message, deps)).resolves.toBe("disabled");
    expect(urls[0]).toContain(`key=${KILL_SWITCH_ENV.KILL_SWITCH_API_KEY}`);
    expect(urls[1]).toContain("/projects/productintelligence-beeb3/");
    expect(logs.at(-1)).toMatchObject({ event: "kill_switch_disabled", trigger: "threshold" });
  });

  it("refuses to build without a valid currency", () => {
    expect(() =>
      killSwitchDeps({ ...KILL_SWITCH_ENV, KILL_SWITCH_CURRENCY: "" }, () => {}),
    ).toThrow(DeployConfigError);
  });
});

describe("createChatFlow", () => {
  it("refuses before touching Vertex or Firestore when the env is incomplete", async () => {
    await expect(createChatFlow({ ...CHAT_ENV, PI_VERTEX_LOCATION: "" })).rejects.toThrow(
      DeployConfigError,
    );
  });

  it("builds the production flow without any network call", async () => {
    await expect(createChatFlow(CHAT_ENV)).resolves.toBeInstanceOf(ChatFlow);
  });

  it("refuses a key-based Vertex setup", async () => {
    await expect(createChatFlow({ ...CHAT_ENV, GEMINI_API_KEY: "k" })).rejects.toThrow(
      "GEMINI_API_KEY",
    );
  });
});

/** A meter that records whether a question was opened. */
class SpyMeter extends Meter {
  readonly started: CallerContext[] = [];
  override startQuestion(caller: CallerContext, label: string) {
    this.started.push(caller);
    return super.startQuestion(caller, label);
  }
}

function realFlow() {
  const store = new MemoryUsageStore({
    ...CONFIG,
    promptVersion: PROMPT_VERSION,
    limits: { ...CONFIG.limits, maxInputTokens: 100_000 },
  });
  const meter = new SpyMeter(store, prices());
  const api = new FakeApi(() => okEnvelope({}));
  const generate = vi.fn<ChatModel["generate"]>(() =>
    Promise.resolve({
      text: "No numbers here.",
      toolCalls: [],
      usage: { input: 10, cachedInput: 0, output: 5, thinking: 0 },
    }),
  );
  const flow = new ChatFlow({
    meter,
    model: { generate },
    registry: new ToolRegistry(TOOLS, api, { evidenceHosts: ["www.sephora.me"] }),
    threads: new MemoryThreadStore(),
  });
  return { flow, meter, api, generate };
}

const request = (role: unknown, data: unknown = { question: "Hi", locale: "en" }) => ({
  auth: { uid: "u1", token: { role }, rawToken: "id-token-1" },
  data,
});

describe("assistantChat request handling (reviewer D2)", () => {
  it.each(["killswitch", "Admin", "", undefined, ["admin"], { role: "admin" }])(
    "refuses role %j with permission-denied before meter.startQuestion",
    async (role) => {
      const { flow, meter, api, generate } = realFlow();
      const error = await handleChat(request(role), flow).catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(CallableRefusal);
      expect(error).toMatchObject({ code: "permission-denied" });
      expect(meter.started).toEqual([]);
      expect(generate).not.toHaveBeenCalled();
      expect(api.calls).toEqual([]);
      expect((error as Error).message).toBe("this account cannot use the assistant");
    },
  );

  it.each([
    ["no auth", { data: {} }],
    ["empty uid", { auth: { uid: "", token: { role: "viewer" }, rawToken: "t" }, data: {} }],
    ["empty token", { auth: { uid: "u1", token: { role: "viewer" }, rawToken: "" }, data: {} }],
  ])("refuses %s as unauthenticated", async (_name, input) => {
    const { flow, meter } = realFlow();
    await expect(handleChat(input, flow)).rejects.toMatchObject({ code: "unauthenticated" });
    expect(meter.started).toEqual([]);
  });

  it.each([null, "Hi", ["Hi"], 7])("refuses a non-object payload %j", async (data) => {
    const { flow, meter } = realFlow();
    await expect(handleChat(request("viewer", data), flow)).rejects.toMatchObject({
      code: "invalid-argument",
    });
    expect(meter.started).toEqual([]);
  });

  it.each(["viewer", "admin"] as const)(
    "lets %s through with the uid, mapped role and raw ID token",
    async (role) => {
      const { flow, meter } = realFlow();
      const answer = await handleChat(request(role), flow);
      expect(answer.status).toBe("answered");
      expect(meter.started).toEqual([{ uid: "u1", role }]);
      expect(callerFrom(request(role))).toEqual({
        caller: { uid: "u1", role },
        idToken: "id-token-1",
      });
    },
  );

  it("leaves strict request parsing to the flow (history is refused, not metered)", async () => {
    const { flow, meter } = realFlow();
    const answer = await handleChat(
      request("viewer", { question: "Hi", locale: "en", history: [] }),
      flow,
    );
    expect(answer).toMatchObject({ status: "unavailable", code: "invalid_question" });
    expect(meter.started).toEqual([]);
  });
});

describe("src/index.ts", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("declares the deploy shape from design §9.4 step 4", async () => {
    vi.stubEnv("FUNCTIONS_CONTROL_API", "true");
    const index = await import("../src/index.js");
    expect(index.budgetKillSwitch.__endpoint).toMatchObject({
      platform: "gcfv2",
      region: ["me-central1"],
      serviceAccountEmail: "pi-killswitch@",
      minInstances: 0,
      maxInstances: 1,
      secretEnvironmentVariables: [{ key: "KILL_SWITCH_PASSWORD" }],
      eventTrigger: {
        eventType: "google.cloud.pubsub.topic.v1.messagePublished",
        eventFilters: { topic: "pi-budget-alerts" },
        retry: true,
      },
    });
    expect(index.assistantChat.__endpoint).toMatchObject({
      region: ["me-central1"],
      serviceAccountEmail: "pi-assistant@",
      minInstances: 0,
      callableTrigger: {},
    });
    // The chat function gets no secret.
    expect(index.assistantChat.__endpoint.secretEnvironmentVariables ?? []).toEqual([]);
    expect(Object.keys(index).sort()).toEqual(Object.values(FUNCTIONS).sort());
  });

  it("adapts refusals to HttpsError and runs the subscriber with the env", async () => {
    vi.stubEnv("FUNCTIONS_CONTROL_API", "true");
    for (const [name, value] of Object.entries(KILL_SWITCH_ENV)) vi.stubEnv(name, value);
    const index = await import("../src/index.js");
    const refused = await Promise.resolve(
      index.assistantChat.run({ data: {}, rawRequest: {} } as never),
    ).catch((caught: unknown) => caught);
    expect(refused).toMatchObject({ code: "unauthenticated", httpErrorCode: { status: 401 } });
    const killSwitch = await Promise.resolve(
      index.assistantChat.run({ ...request("killswitch"), rawRequest: {} } as never),
    ).catch((caught: unknown) => caught);
    expect(killSwitch).toMatchObject({ code: "permission-denied" });
    const stale = { data: "", attributes: {}, publishTime: "2020-01-01T00:00:00Z" };
    await expect(
      Promise.resolve(index.budgetKillSwitch.run({ data: { message: stale } } as never)),
    ).resolves.toBeUndefined();
  });

  it("refuses to load in a container whose settings are invalid", async () => {
    vi.stubEnv("FUNCTIONS_CONTROL_API", "");
    vi.stubEnv("FUNCTION_TARGET", FUNCTIONS.killSwitch);
    for (const [name, value] of Object.entries(KILL_SWITCH_ENV)) vi.stubEnv(name, value);
    vi.stubEnv("KILL_SWITCH_CURRENCY", "usd");
    await expect(import("../src/index.js")).rejects.toThrow(
      "KILL_SWITCH_CURRENCY is missing or invalid",
    );
  });
});
