/**
 * Tool contract (design §4). Each tool is a thin, read-only client of one service-layer
 * endpoint: a strict input schema and a pure mapping from input to request. Metrics are never
 * computed here (coordinator ruling: one implementation, pi_metrics).
 */
import type { z } from "zod";

import type { ApiRequest } from "../api/client.js";

export const ROLES = ["viewer", "admin"] as const;
export type Role = (typeof ROLES)[number];

/** Who is asking. The ID token travels separately so it never lands in a tool result or log. */
export interface CallerContext {
  readonly uid: string;
  readonly role: Role;
}

export interface ToolDef<I extends z.ZodTypeAny> {
  readonly name: string;
  readonly version: string;
  /** Shown to the model as the tool description. */
  readonly description: string;
  readonly minRole: Role;
  readonly input: I;
  request(input: z.output<I>): ApiRequest;
}

/** Erased form for the registry; each tool keeps its own precise input type. */
export interface AnyToolDef {
  readonly name: string;
  readonly version: string;
  readonly description: string;
  readonly minRole: Role;
  readonly input: z.ZodTypeAny;
  /** Only ever called with the output of `input.safeParse`. */
  request(input: never): ApiRequest;
}

export function defineTool<I extends z.ZodTypeAny>(def: ToolDef<I>): ToolDef<I> {
  return def;
}
