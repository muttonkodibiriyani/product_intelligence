import { RECAPTCHA_SITE } from '.';
import type { ChatAnswer, ChatProgress } from './types';

/** Where `assistantChat` runs (apps/assistant `REGION`). */
export const ASSISTANT_REGION = 'me-central1';
/** A little over the function's 120 s timeout, so the server's answer or error arrives first. */
export const CALL_TIMEOUT_MS = 130_000;

/** The callable's input (apps/assistant `ChatRequestSchema`, strict). History is never sent. */
export interface ChatRequest {
  readonly question: string;
  readonly locale: 'en' | 'ar';
  readonly threadId?: string;
}

export interface AskOptions {
  readonly signal?: AbortSignal;
  readonly onProgress?: (progress: ChatProgress) => void;
}

export type Ask = (request: ChatRequest, options?: AskOptions) => Promise<ChatAnswer>;

/** Thrown for a response that is not the answer contract; shown as the generic error. */
export class BadResponse extends Error {}

const STAGES = new Set(['thinking', 'verifying', 'retrying']);
const TOOL_STATUSES = new Set(['ok', 'not_enough_data', 'error']);
const ANSWER_STATUSES = new Set(['answered', 'unverified', 'unavailable']);

export function isProgress(value: unknown): value is ChatProgress {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v.type === 'status') return typeof v.stage === 'string' && STAGES.has(v.stage);
  return (
    v.type === 'tool' &&
    typeof v.name === 'string' &&
    typeof v.status === 'string' &&
    TOOL_STATUSES.has(v.status)
  );
}

/** Shape check of the fields the page reads; anything else is refused, never half-rendered. */
export function isChatAnswer(value: unknown): value is ChatAnswer {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.status === 'string' &&
    ANSWER_STATUSES.has(v.status) &&
    typeof v.answerMd === 'string' &&
    ['citations', 'caveats', 'productIds', 'notEnoughData', 'toolResults'].every((k) => Array.isArray(v[k]))
  );
}

let client: Promise<Ask> | undefined;

/**
 * The callable client, loaded on first use so the Functions and App Check SDKs stay out of the
 * page until a question is sent. App Check uses reCAPTCHA Enterprise on the app Auth started.
 */
export function assistantClient(): Promise<Ask> {
  return (client ??= (async () => {
    const [{ getApp }, appCheck, functions] = await Promise.all([
      import('@firebase/app'),
      import('@firebase/app-check'),
      import('@firebase/functions'),
    ]);
    const app = getApp();
    appCheck.initializeAppCheck(app, {
      provider: new appCheck.ReCaptchaEnterpriseProvider(RECAPTCHA_SITE),
      isTokenAutoRefreshEnabled: true,
    });
    const call = functions.httpsCallable<ChatRequest, unknown, unknown>(
      functions.getFunctions(app, ASSISTANT_REGION),
      'assistantChat',
      { timeout: CALL_TIMEOUT_MS },
    );
    const ask: Ask = async (request, options = {}) => {
      const result = await call.stream(request, { signal: options.signal });
      for await (const chunk of result.stream) if (isProgress(chunk)) options.onProgress?.(chunk);
      const answer = await result.data;
      if (!isChatAnswer(answer)) throw new BadResponse('not a chat answer');
      return answer;
    };
    return ask;
  })().catch((cause: unknown) => {
    client = undefined;
    throw cause;
  }));
}

export type ChatError = 'signedOut' | 'noAccess' | 'invalid' | 'network' | 'timeout' | 'generic';

/** Callable errors mapped to the few notes the page shows. Messages are never displayed. */
export function chatErrorKey(e: unknown): ChatError {
  const code = (e as { code?: unknown } | null)?.code;
  switch (code) {
    case 'functions/unauthenticated':
      return 'signedOut';
    case 'functions/permission-denied':
      return 'noAccess';
    case 'functions/invalid-argument':
      return 'invalid';
    case 'functions/unavailable':
      return 'network';
    case 'functions/deadline-exceeded':
      return 'timeout';
    default:
      return 'generic';
  }
}
