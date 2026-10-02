/**
 * The `assistantChat` answer contract, mirrored from `apps/assistant` (`src/flows/chat.ts`,
 * `src/tools/registry.ts`). Only the fields the page renders. Untrusted strings arrive
 * wrapped and Markdown-escaped; render them with `plain()`, never as Markdown or HTML.
 */
export interface Untrusted {
  readonly untrusted: string;
}

export interface UntrustedBilingual {
  readonly en: Untrusted;
  readonly ar: Untrusted;
}

export interface Citation {
  readonly tool: string;
  readonly toolVersion: string;
  readonly apiVersion: string;
  readonly metricVersion: string;
  readonly datasetGeneration: string;
  readonly cutoff: string;
  readonly market: string;
  readonly currency: string;
  readonly filters: Readonly<Record<string, unknown>>;
  readonly cohort: { readonly description: Untrusted; readonly n: number } | null;
}

export type Sanitised =
  string | number | boolean | null | Untrusted | Sanitised[] | { [key: string]: Sanitised };

export interface ToolEnvelope {
  readonly status: 'ok' | 'not_enough_data';
  readonly data?: Sanitised;
  readonly notEnoughData?: { readonly reason: string; readonly detail: UntrustedBilingual };
  readonly citation: Citation;
  readonly caveats: readonly (UntrustedBilingual & { readonly code: string })[];
}

export type AnswerStatus = 'answered' | 'unverified' | 'unavailable';

export interface ChatAnswer {
  readonly status: AnswerStatus;
  readonly code?: string;
  readonly answerMd: string;
  readonly language: 'en' | 'ar';
  readonly citations: readonly Citation[];
  readonly caveats: readonly UntrustedBilingual[];
  readonly productIds: readonly string[];
  readonly notEnoughData: readonly {
    readonly tool: string;
    readonly reason: string;
    readonly detail: UntrustedBilingual;
  }[];
  readonly toolResults: readonly ToolEnvelope[];
  readonly costUsd: string;
}

/** Streamed while a question runs (design §11). Model text is never streamed. */
export type ChatProgress =
  | { readonly type: 'status'; readonly stage: 'thinking' | 'verifying' | 'retrying' }
  | {
      readonly type: 'tool';
      readonly name: string;
      readonly status: 'ok' | 'not_enough_data' | 'error';
      readonly code?: string;
    };

const ESCAPED = /\\([\\`*_{}[\]()#+!|<>~&"])/g;

/** Undo the server's Markdown escaping, for display as plain text. */
export const unescapeMd = (text: string): string => text.replace(ESCAPED, '$1');

export const plain = (value: Untrusted): string => unescapeMd(value.untrusted);

export const isUntrusted = (value: unknown): value is Untrusted =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.keys(value).length === 1 &&
  typeof (value as { untrusted?: unknown }).untrusted === 'string';
