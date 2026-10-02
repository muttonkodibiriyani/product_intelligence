/**
 * The one line each Prices chart leads with, computed from the same data the chart draws: no
 * figure here that is not in the chart. Null when the data cannot carry the sentence.
 */
import { num, type Summary } from '@/lib/api/summary';
import type { Schemas } from '@/lib/api/types';
import { gapBinSign, gapHistBins, histBins, ladderRows } from '../widgets/model';

/** The price band holding the most products, and its share of all products in the histogram. */
export function histTakeaway(h: Summary['priceHist']) {
  const bins = histBins(h);
  const total = bins.reduce((s, b) => s + b.count, 0);
  if (bins.length === 0 || total <= 0) return null;
  const top = bins.reduce((a, b) => (b.count > a.count ? b : a));
  return { lo: top.lo, hi: top.hi, share: top.count / total, count: top.count, total };
}

/** The categories with the lowest and the highest median; nothing to say with fewer than two. */
export function ladderTakeaway(ladder: Summary['ladder']) {
  const rows = ladderRows(ladder);
  if (rows.length < 2) return null;
  const byMedian = [...rows].sort((a, b) => a.v[2] - b.v[2]);
  const low = byMedian[0]!;
  const high = byMedian[byMedian.length - 1]!;
  return {
    low: { category: low.category, median: low.p50 },
    high: { category: high.category, median: high.p50 },
  };
}

/** Among the `top` largest brands the chart ranks, the dearest and the cheapest by median. */
export function brandTakeaway(brands: Summary['brandPrice'], top: number) {
  // The same rows the chart draws: the largest brands by products, those with a usable median.
  const rows = (brands ?? []).slice(0, top).filter((b) => num(b.median.amount) > 0);
  if (rows.length < 2) return null;
  const sorted = [...rows].sort((a, b) => num(a.median.amount) - num(b.median.amount));
  const low = sorted[0]!;
  const high = sorted[sorted.length - 1]!;
  return {
    n: rows.length,
    high: { brand: high.brand, median: high.median },
    low: { brand: low.brand, median: low.median },
  };
}

/**
 * How the matched pairs split by the sign of their gap band: the other retailer dearer (bands
 * above zero), cheaper (below), or in a band that straddles zero. Shares of the pairs counted.
 */
export function gapTakeaway(h: Schemas['GapHistogram'] | null | undefined) {
  const bins = gapHistBins(h);
  const n = bins.reduce((s, b) => s + b.count, 0);
  if (bins.length === 0 || n <= 0) return null;
  const sum = (sign: -1 | 0 | 1) =>
    bins.filter((b) => gapBinSign(b) === sign).reduce((s, b) => s + b.count, 0);
  const dearer = sum(1);
  const cheaper = sum(-1);
  const same = sum(0);
  return { n, dearer: dearer / n, cheaper: cheaper / n, same: same / n };
}
