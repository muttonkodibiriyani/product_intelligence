/**
 * The service layer's response envelope (provisional, agreed with the Deep Coder). Per-endpoint
 * `data` schemas will be generated from the API's OpenAPI 3.1 document (docs/contracts/). Until
 * then `data` is validated structurally and passed through the fail-closed sanitiser.
 */
import { z } from "zod";

export const NOT_ENOUGH_DATA_REASONS = [
  "capability_off",
  "field_not_collected",
  "retailer_blocked",
  "retailer_partial",
  "cohort_too_small",
  "matches_unreviewed",
  "no_match",
  "not_in_scope",
  "currency_mismatch",
] as const;
export type NotEnoughDataReason = (typeof NOT_ENOUGH_DATA_REASONS)[number];

const bilingual = z.object({ en: z.string().max(2000), ar: z.string().max(2000) });
export type Bilingual = z.infer<typeof bilingual>;

const identifier = z.string().regex(/^[A-Za-z0-9_.:-]{1,200}$/);

export const EvidenceSchema = z.object({
  productId: identifier,
  retailer: z.string().regex(/^[a-z][a-z0-9_]{1,62}$/),
  url: z.string().nullable(),
  capturedAt: z.string().datetime({ offset: true }),
  runId: identifier.optional(),
  source: identifier.optional(),
});
export type Evidence = z.infer<typeof EvidenceSchema>;

export const EnvelopeSchema = z
  .object({
    status: z.enum(["ok", "not_enough_data"]),
    data: z.unknown().optional(),
    reason: z.enum(NOT_ENOUGH_DATA_REASONS).optional(),
    detail: bilingual.optional(),
    cohort: z.object({ description: z.string().max(500), n: z.number().int().nonnegative() }),
    caveats: z.array(bilingual).max(20),
    evidence: z.array(EvidenceSchema).max(20),
    meta: z.object({
      generation: identifier,
      cutoff: z.string().datetime({ offset: true }),
      market: z.string().regex(/^[A-Z]{2}$/),
      currency: z.string().regex(/^[A-Z]{3}$/),
      apiVersion: identifier,
      metricVersion: identifier,
      endpoint: identifier,
      scope: identifier,
    }),
  })
  .superRefine((value, ctx) => {
    if (value.status === "ok" && value.data === undefined) {
      ctx.addIssue({ code: "custom", path: ["data"], message: "ok without data" });
    }
    if (value.status === "not_enough_data" && (!value.reason || !value.detail)) {
      ctx.addIssue({
        code: "custom",
        path: ["reason"],
        message: "not_enough_data needs reason+detail",
      });
    }
  });
export type ApiEnvelope = z.infer<typeof EnvelopeSchema>;
