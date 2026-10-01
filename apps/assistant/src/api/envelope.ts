/**
 * The service layer's response envelope, as published in `docs/contracts/pi-api.openapi.json`
 * (`Envelope_*`, `ApiMeta`, `Cohort`, `CaveatView`). Per-endpoint `data` is validated
 * structurally and passed through the fail-closed sanitiser; `test/contract.test.ts` runs every
 * golden response through the tools.
 *
 * Unknown keys are stripped rather than rejected, so an additive API change does not take the
 * assistant down; a changed or missing required field fails closed (`upstream_invalid`).
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
  "not_applicable",
  // API 1.5.0: an imported retailer's was-prices are unverified, so its promotions are withheld.
  "was_price_unverified",
] as const;
export type NotEnoughDataReason = (typeof NOT_ENOUGH_DATA_REASONS)[number];

const bilingual = z.object({ en: z.string().max(2000), ar: z.string().max(2000) });
export type Bilingual = z.infer<typeof bilingual>;

const identifier = z.string().regex(/^[A-Za-z0-9_.:-]{1,200}$/);

/** Upstream caveats accepted; more is an invalid body (`upstream_invalid`). */
export const MAX_UPSTREAM_CAVEATS = 200;

/** Machine-readable caveat codes; the API renders `en`/`ar` text per code. */
const caveatCode = z.string().regex(/^[a-z][a-z0-9_]{0,40}$/);

export const EnvelopeSchema = z
  .object({
    status: z.enum(["ok", "not_enough_data"]),
    data: z.unknown(),
    reason: z.enum(NOT_ENOUGH_DATA_REASONS).nullish(),
    detail: bilingual.nullish(),
    cohort: z
      .object({ description: z.string().max(500), n: z.number().int().nonnegative() })
      .nullish(),
    // pi_metrics v3 adds one size_labels_differ per distinct label pair, uncapped; the registry
    // lists the first MAX_CAVEATS. This bound only rejects an absurd body.
    caveats: z
      .array(bilingual.extend({ code: caveatCode }))
      .max(MAX_UPSTREAM_CAVEATS)
      .default([]),
    meta: z.object({
      generation: identifier,
      cutoff: z.string().datetime({ offset: true }),
      market: z.string().regex(/^[A-Z]{2}$/),
      currency: z.string().regex(/^[A-Z]{3}$/),
      apiVersion: identifier,
      metricVersion: identifier,
      endpoint: identifier,
      scope: identifier,
      filters: z.record(z.unknown()),
    }),
  })
  .superRefine((value, ctx) => {
    if (value.status === "ok" && (value.data === undefined || value.data === null)) {
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
