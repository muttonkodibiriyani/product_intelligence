/**
 * The `assistantChat` callable's request handling, framework-free so it is tested without the
 * Functions runtime (`src/index.ts` only adapts it). Who may ask is decided here, before the
 * chat flow, the meter or any tool runs (design §6, reviewer D2): the token's `role` claim
 * becomes a caller role only through `callerRole`, so `killswitch` or any other claim is refused
 * and never counted, metered or treated as a viewer.
 */
import type { ChatAnswer, ChatFlow, ChatInput } from "../flows/chat.js";
import { type CallerContext, callerRole } from "../tools/types.js";

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

export async function handleChat(
  request: CallableRequestLike,
  flow: Pick<ChatFlow, "answer">,
): Promise<ChatAnswer> {
  const { caller, idToken } = callerFrom(request);
  const data = request.data;
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new CallableRefusal("invalid-argument");
  }
  // The flow parses strictly (unknown keys such as `history` are refused there).
  return flow.answer(data as ChatInput, caller, idToken);
}
