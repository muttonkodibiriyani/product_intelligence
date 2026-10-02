/**
 * Tool contract (design §4). Each tool is a thin, read-only client of one service-layer
 * endpoint: a strict input schema and a pure mapping from input to request. Metrics are never
 * computed here (coordinator ruling: one implementation, pi_metrics).
 */
import type { z } from "zod";

import type { ApiRequest } from "../api/client.js";

export const ROLES = ["viewer", "admin"] as const;
export type Role = (typeof ROLES)[number];

/**
 * The only way a token's `role` claim becomes a caller role (the callable uses this). Anything
 * but exactly viewer or admin, including the kill switch's `killswitch`, maps to null and is
 * refused before the meter or any tool runs.
 */
export function callerRole(claim: unknown): Role | null {
  return ROLES.find((role) => role === claim) ?? null;
}

/** Who is asking. The ID token travels separately so it never lands in a tool result or log. */
export interface CallerContext {
  readonly uid: string;
  readonly role: Role;
}

/**
 * A tool's slice of a response: `data` replaces the envelope data; `withheld` turns an ok
 * envelope into not_enough_data with the service's own reason (e.g. a /summary section it
 * withheld), so the answer says so instead of reading a null as zero.
 */
export interface ToolView {
  readonly data: unknown;
  readonly withheld?: string;
}

export interface ToolDef<I extends z.ZodTypeAny> {
  readonly name: string;
  readonly version: string;
  /** Shown to the model as the tool description. */
  readonly description: string;
  readonly minRole: Role;
  readonly input: I;
  /**
   * The row list a `limit` can cut (API 1.1.0). When the response says `truncated`, the registry
   * adds `shown` and a `truncated` caveat so the answer can say "top N of total".
   */
  readonly listKey?: string;
  request(input: z.output<I>): ApiRequest;
  /** Picks this tool's part of the response (a pure projection; nothing is computed). */
  view?(data: unknown): ToolView;
}

/** Erased form for the registry; each tool keeps its own precise input type. */
export interface AnyToolDef {
  readonly name: string;
  readonly version: string;
  readonly description: string;
  readonly minRole: Role;
  readonly input: z.ZodTypeAny;
  readonly listKey?: string;
  /** Only ever called with the output of `input.safeParse`. */
  request(input: never): ApiRequest;
  view?(data: unknown): ToolView;
}

export function defineTool<I extends z.ZodTypeAny>(def: ToolDef<I>): ToolDef<I> {
  return def;
}
