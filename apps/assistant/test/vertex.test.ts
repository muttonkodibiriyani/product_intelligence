import type { GenerateContentParameters, GenerateContentResponse } from "@google/genai";
import { describe, expect, it } from "vitest";

import type { ModelRequest } from "../src/flows/model.js";
import {
  ALLOWED_PROJECT,
  FORBIDDEN_ENV,
  type GenerateContentClient,
  VertexChatModel,
  VertexConfigError,
  buildRequest,
  checkVertexEnvironment,
  parseReply,
} from "../src/flows/vertex.js";

const OPTIONS = { project: ALLOWED_PROJECT, location: "us-central1" };

const REQUEST: ModelRequest = {
  model: "gemini-2.5-flash",
  system: "rules",
  turns: [
    { role: "user", text: "q" },
    {
      role: "model",
      text: "",
      toolCalls: [{ id: "c1", name: "compare", args: { ids: ["a", "b"] } }],
    },
    {
      role: "tool",
      results: [{ call: { id: "c1", name: "compare", args: {} }, output: { status: "ok" } }],
    },
    { role: "model", text: "partial", toolCalls: [{ name: "launches", args: "not-an-object" }] },
  ],
  tools: [{ name: "compare", description: "d", parameters: { type: "object" } }],
  limits: { maxInputTokens: 10_000, maxOutputTokens: 1_500, thinkingBudget: 500 },
  temperature: 0.2,
};

const response = (value: unknown) => value as GenerateContentResponse;

describe("checkVertexEnvironment", () => {
  it("accepts the allowed project with no key variables", () => {
    expect(() => {
      checkVertexEnvironment(OPTIONS, { GOOGLE_CLOUD_PROJECT: ALLOWED_PROJECT, EMPTY: "" });
    }).not.toThrow();
  });

  it.each(FORBIDDEN_ENV)("refuses when %s is set", (name) => {
    expect(() => {
      checkVertexEnvironment(OPTIONS, { [name]: "x" });
    }).toThrow(VertexConfigError);
  });

  it("ignores forbidden variables that are set but empty", () => {
    expect(() => {
      checkVertexEnvironment(OPTIONS, { GEMINI_API_KEY: "" });
    }).not.toThrow();
  });

  it("refuses any other project and malformed locations", () => {
    expect(() => {
      checkVertexEnvironment({ ...OPTIONS, project: "other-project" }, {});
    }).toThrow(/project must be/);
    expect(() => {
      checkVertexEnvironment({ ...OPTIONS, location: "us-central1.evil.example/" }, {});
    }).toThrow(/location/);
  });

  it("create refuses before building a client", () => {
    expect(() => VertexChatModel.create(OPTIONS, { GOOGLE_API_KEY: "k" })).toThrow(
      VertexConfigError,
    );
  });
});

describe("buildRequest", () => {
  it("maps turns, tools and limits, with automatic calling off", () => {
    const params = buildRequest(REQUEST);
    expect(params.model).toBe("gemini-2.5-flash");
    expect(params.config).toMatchObject({
      systemInstruction: "rules",
      temperature: 0.2,
      maxOutputTokens: 1_500,
      thinkingConfig: { thinkingBudget: 500 },
      candidateCount: 1,
      automaticFunctionCalling: { disable: true },
      tools: [
        {
          functionDeclarations: [
            { name: "compare", description: "d", parametersJsonSchema: { type: "object" } },
          ],
        },
      ],
    });
    expect(params.contents).toEqual([
      { role: "user", parts: [{ text: "q" }] },
      {
        role: "model",
        parts: [{ functionCall: { id: "c1", name: "compare", args: { ids: ["a", "b"] } } }],
      },
      {
        role: "user",
        parts: [
          {
            functionResponse: { id: "c1", name: "compare", response: { output: { status: "ok" } } },
          },
        ],
      },
      {
        role: "model",
        parts: [{ text: "partial" }, { functionCall: { name: "launches", args: {} } }],
      },
    ]);
  });

  it("omits tools when none are offered", () => {
    expect(buildRequest({ ...REQUEST, tools: [] }).config?.tools).toBeUndefined();
  });
});

describe("parseReply", () => {
  it("joins text, drops thoughts and maps calls and usage", () => {
    const reply = parseReply(
      response({
        candidates: [
          {
            content: {
              parts: [
                { text: "secret plan", thought: true },
                { text: "Hello " },
                { text: "world" },
                { functionCall: { id: "x", name: "compare", args: { limit: 5 } } },
                { functionCall: {} },
              ],
            },
          },
        ],
        usageMetadata: {
          promptTokenCount: 100,
          toolUsePromptTokenCount: 20,
          cachedContentTokenCount: 10,
          candidatesTokenCount: 30,
          thoughtsTokenCount: 40,
        },
      }),
    );
    expect(reply.text).toBe("Hello world");
    expect(reply.toolCalls).toEqual([
      { id: "x", name: "compare", args: { limit: 5 } },
      { name: "", args: {} },
    ]);
    expect(reply.usage).toEqual({ input: 120, cachedInput: 10, output: 30, thinking: 40 });
  });

  it("reports NaN usage when metadata is missing, so the meter charges the ceiling", () => {
    const none = parseReply(response({ candidates: [] }));
    expect(none.text).toBe("");
    expect(Number.isNaN(none.usage.input)).toBe(true);
    expect(Number.isNaN(none.usage.output)).toBe(true);
    const partial = parseReply(response({ usageMetadata: { promptTokenCount: 5 } }));
    expect(partial.usage.input).toBe(5);
    expect(Number.isNaN(partial.usage.output)).toBe(true);
  });
});

describe("VertexChatModel", () => {
  it("sends the built request through the client", async () => {
    const seen: GenerateContentParameters[] = [];
    const client: GenerateContentClient = {
      generateContent: (params) => {
        seen.push(params);
        return Promise.resolve(
          response({
            candidates: [{ content: { parts: [{ text: "ok" }] } }],
            usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1 },
          }),
        );
      },
    };
    const reply = await new VertexChatModel(client).generate(REQUEST);
    expect(reply.text).toBe("ok");
    expect(seen[0]).toEqual(buildRequest(REQUEST));
  });
});
