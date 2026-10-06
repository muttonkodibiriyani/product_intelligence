/**
 * The `assistantChat` callable's request handling, framework-free so it is tested without the
 * Functions runtime (`src/index.ts` only adapts it). Who may ask is decided here, before the
 * chat flow, the meter or any tool runs (design §6, reviewer D2): the token's `role` claim
 * becomes a caller role only through `callerRole`, so `killswitch` or any other claim is refused
 * and never counted, metered or treated as a viewer.
 */
import type { ChatAnswer, ChatFlow, ChatInput, ProgressSink } from "../flows/chat.js";
import { type CallerContext, type Role, callerRole } from "../tools/types.js";

/** The parts of a verified callable request this handler reads (`CallableRequest` fits). */
export interface CallableRequestLike {
  readonly auth?:
    | {
        readonly uid: string;
        readonly token: Readonly<Record<string, unknown>>;
        readonly rawToken: string;
      }
    | undefined;
  readonly data: unknown;
}

export type RefusalCode = "unauthenticated" | "permission-denied" | "invalid-argument";

/** Mapped to `HttpsError` by the adapter. Messages are fixed text; no claim value is echoed. */
export class CallableRefusal extends Error {
  constructor(readonly code: RefusalCode) {
    super(
      {
        unauthenticated: "sign in to use the assistant",
        "permission-denied": "this account cannot use the assistant",
        "invalid-argument": "invalid request",
      }[code],
    );
    this.name = "CallableRefusal";
  }
}

export function callerFrom(request: CallableRequestLike): {
  readonly caller: CallerContext;
  readonly idToken: string;
} {
  const auth = request.auth;
  if (auth === undefined || auth.uid === "" || auth.rawToken === "") {
    throw new CallableRefusal("unauthenticated");
  }
  const role = callerRole(auth.token.role);
  if (role === null) throw new CallableRefusal("permission-denied");
  return { caller: { uid: auth.uid, role }, idToken: auth.rawToken };
}

/** One structured log line per answered request; see `answerLogEntry`. */
export type AnswerLog = (entry: Readonly<Record<string, unknown>>) => void;

/**
 * What the callable logs about an answer: codes and counts only. The question, answer text,
 * tool names and arguments (model text), uid and thread are never logged. Without this line a
 * refusal such as `config_invalid` left no trace in the logs.
 */
export function answerLogEntry(answer: ChatAnswer, role: Role): Record<string, unknown> {
  const tools = { ok: 0, not_enough_data: 0, error: 0 };
  const toolErrors = new Set<string>();
  for (const record of answer.toolCalls) {
    tools[record.status] += 1;
    if (record.status === "error" && record.code !== undefined) toolErrors.add(record.code);
  }
  return {
    event: "assistant_answer",
    severity: answer.status === "unavailable" ? "WARNING" : "INFO",
    status: answer.status,
    code: answer.code ?? null,
    role,
    model: answer.model,
    promptVersion: answer.promptVersion,
    modelCalls: answer.modelCalls,
    tools,
    toolErrors: [...toolErrors].sort(),
    costUsd: answer.costUsd,
  };
}

export async function handleChat(
  request: CallableRequestLike,
  flow: Pick<ChatFlow, "answer">,
  onProgress?: ProgressSink,
  log?: AnswerLog,
): Promise<ChatAnswer> {
  const { caller, idToken } = callerFrom(request);
  const data = request.data;
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new CallableRefusal("invalid-argument");
  }
  // The flow parses strictly (unknown keys such as `history` are refused there).
  const answer = await flow.answer(data as ChatInput, caller, idToken, onProgress);
  try {
    log?.(answerLogEntry(answer, caller.role));
  } catch {
    // Logging is diagnostics only: a failed write never costs the caller their answer.
  }
  return answer;
}
