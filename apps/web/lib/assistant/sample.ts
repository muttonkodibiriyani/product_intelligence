import type { Summary } from '@/lib/api/summary';
import type { Envelope } from '@/lib/api/types';
import { type AppLocale, formatMoney } from '@/lib/money';
import { escapeMd } from './markdown';
import type { ChatAnswer } from './types';

type Sentence = 'catalogue' | 'priced' | 'median' | 'promo';
type Translate = (key: Sentence, values: Record<string, string>) => string;

/**
 * The page's sample answer: a few facts from a real /api/v1/summary response, in the answer
 * layout. Every number is the API's own value (counts and decimal strings as sent, money via
 * formatMoney); there is no model text. Null unless the response is ok and has a product count,
 * so a failed or empty response shows no sample at all.
 */
export function sampleAnswer(env: Envelope<Summary>, t: Translate, locale: AppLocale): ChatAnswer | null {
  const s = env.data;
  if (env.status !== 'ok' || !s || s.products === null) return null;
  const retailer = escapeMd(s.retailer);
  const lines = [t('catalogue', { retailer, products: String(s.products) })];
  if (s.priced !== null) lines.push(t('priced', { priced: String(s.priced) }));
  if (s.medianPrice) lines.push(t('median', { median: escapeMd(formatMoney(s.medianPrice, locale)) }));
  if (s.promoSharePct !== null) lines.push(t('promo', { pct: escapeMd(s.promoSharePct) }));
  const { meta, cohort } = env;
  return {
    status: 'answered',
    answerMd: lines.map((l) => `- ${l}`).join('\n'),
    language: locale,
    citations: [
      {
        tool: 'summary',
        toolVersion: '',
        apiVersion: meta.apiVersion,
        metricVersion: meta.metricVersion,
        datasetGeneration: meta.generation,
        cutoff: meta.cutoff,
        market: meta.market,
        currency: meta.currency,
        filters: meta.filters,
        cohort: cohort ? { description: { untrusted: escapeMd(cohort.description) }, n: cohort.n } : null,
      },
    ],
    caveats: [],
    productIds: [],
    notEnoughData: [],
    toolResults: [],
    costUsd: '0',
  };
}
