'use client';

import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import {
  EXAMPLES_SHOWN,
  fillArgs,
  findingId,
  list,
  messageArgs,
  moneyText,
  paramText,
  type Example,
  type Finding,
  type Namers,
} from '@/lib/findings';
import { formatCount } from '@/lib/format';
import { productHref } from '../../explore/product-table';
import { monogram, RowThumb } from '../../explore/row-thumb';
import { RetailerDot } from '../../ui/retailer-dot';
import { FindingChart } from './finding-chart';
import { known } from './known';

/** The shops a finding is about: every message may name them, whatever the finding sent. */
export type Pair = { focus: string; rival: string; thirds: readonly string[] };

/** One finding's words in the page's language: its KPI, tile and headline, decision to owner. */
export function useFindingText(f: Finding, names: Namers, pair: Pair) {
  const t = useTranslations('insights.findings');
  const tr = useTranslations('reasons');
  const locale = useLocale();
  const args: Record<string, string> = {
    focus: names.shop(pair.focus),
    rival: names.shop(pair.rival),
    shop: names.shop(pair.focus),
    threshold: formatCount(f.threshold, locale),
    ...messageArgs(f, locale, names),
  };
  const say = (part: string) => {
    const key = `items.${f.key}.${part}` as const;
    return t(key, fillArgs(t.raw(key) as string, args));
  };
  const shown = f.status === 'ok';
  const kpi = shown && f.figure && f.figure.kind !== 'missing' ? paramText(f.figure, locale, names) : '';
  return {
    id: findingId(f.key),
    kpi,
    tile: say('tile'),
    headline: shown ? say('headline') : t('withheld', { reason: f.reason ? known(tr, '', f.reason) : '' }),
    shown,
    say,
  };
}

/**
 * One finding as the design (6 Oct) lays it out: rank, match chips and the (i); the KPI inside a
 * headline of at most twelve words; the chart beside the verb-first action, its owner and up to four
 * products; the question and the evidence folded under "Why we say this". A withheld finding
 * keeps its place and rank and says why, with no number.
 */
export function FindingCard({ finding: f, names, pair }: { finding: Finding; names: Namers; pair: Pair }) {
  const t = useTranslations('insights.findings');
  const text = useFindingText(f, names, pair);
  return (
    <article
      id={text.id}
      aria-labelledby={`${text.id}-h`}
      data-finding={f.key}
      className="scroll-mt-3 rounded-xl border border-line px-4 pt-4 pb-3.5 sm:px-[18px]"
    >
      <div className="flex min-h-[22px] flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-ink-2 tabular-nums">{t('rank', { rank: f.rank })}</span>
        {f.chips.map((c) => (
          <span
            key={`${c.code}-${c.retailer}`}
            className="rounded-full border border-[#ead9a8] bg-warn-bg px-2 py-px text-xs text-warn"
          >
            {t(`chips.${c.code}`, { shop: names.shop(c.retailer) })}
          </span>
        ))}
        <About finding={f} names={names} pair={pair} />
      </div>
      <h4
        id={`${text.id}-h`}
        className="mt-1.5 mb-3.5 max-w-[46em] text-[17px] leading-snug font-semibold sm:text-[19px]"
      >
        {text.kpi && (
          <>
            <strong className="me-1 align-[-3px] text-[28px] leading-none font-bold tracking-tight tabular-nums sm:text-[34px]">
              <bdi>{text.kpi}</bdi>
            </strong>{' '}
          </>
        )}
        {text.headline}
      </h4>
      {text.shown && (
        <>
          <div className="grid items-start gap-x-7 gap-y-3 lg:grid-cols-[minmax(0,3fr)_minmax(260px,2fr)]">
            {f.chart ? <FindingChart finding={f} names={names} caption={text.say('cap')} /> : <div />}
            <aside className="min-w-0">
              <p className="mb-3.5 text-[15px] leading-normal">
                <span className="mb-0.5 block text-xs font-semibold tracking-[.06em] text-ink-2 uppercase rtl:text-[13px] rtl:tracking-normal rtl:normal-case">
                  {t('action')}
                </span>
                {text.say('action')}{' '}
                <span className="whitespace-nowrap text-ink-2">— {text.say('owner')}</span>
              </p>
              {f.examples.length > 0 && (
                <>
                  <p className="mb-2 text-xs font-semibold tracking-[.06em] text-ink-2 uppercase rtl:text-[13px] rtl:tracking-normal rtl:normal-case">
                    {t('products')}
                  </p>
                  <ul className="grid grid-cols-4 gap-2.5">
                    {f.examples.slice(0, EXAMPLES_SHOWN).map((e) => (
                      <Product key={`${e.retailer}-${e.id}`} e={e} names={names} />
                    ))}
                  </ul>
                </>
              )}
            </aside>
          </div>
          <details className="mt-3 border-t border-line pt-2">
            <summary className="cursor-pointer text-[13px] font-semibold text-ink-2 hover:text-ink">
              {t('why')}
            </summary>
            <p className="mt-2 max-w-[72em] text-sm text-ink">
              <span className="me-1.5 text-xs font-semibold tracking-[.06em] text-ink-2 uppercase rtl:text-[13px] rtl:tracking-normal rtl:normal-case">
                {t('question')}
              </span>
              {text.say('decision')}
            </p>
            <p className="mt-2 max-w-[72em] text-sm text-ink">{text.say('evidence')}</p>
          </details>
        </>
      )}
    </article>
  );
}

/** The (i): how many, of what, matched how, on which price, above what threshold, from which shops. */
function About({ finding: f, names, pair }: { finding: Finding; names: Namers; pair: Pair }) {
  const t = useTranslations('insights.findings');
  const locale = useLocale();
  const id = `${findingId(f.key)}-about`;
  const left = new Set(f.chips.map((c) => c.retailer));
  const read = [pair.focus, pair.rival, ...pair.thirds].filter((s) => !left.has(s)).map(names.shop);
  const rows: [string, string][] = [
    [
      t('tip.n'),
      f.of === null
        ? formatCount(f.n, locale)
        : t('tip.nOf', { n: formatCount(f.n, locale), of: formatCount(f.of, locale) }),
    ],
    [t('tip.match'), known(t, 'match', f.match)],
    [t('tip.basis'), known(t, 'basis', f.basis)],
    [t('tip.threshold'), t(`items.${f.key}.threshold`, { threshold: formatCount(f.threshold, locale) })],
    [t('tip.coverage'), list(read, locale)],
  ];
  return (
    <span className="tipwrap ms-auto">
      <button
        type="button"
        aria-label={t('about')}
        aria-describedby={id}
        onKeyDown={(e) => e.key === 'Escape' && e.currentTarget.blur()}
        className="size-[22px] rounded-full border border-ink-3 bg-surface p-0 font-serif text-xs font-semibold text-ink-2 italic hover:border-ink hover:text-ink"
      >
        i
      </button>
      <span role="tooltip" id={id} data-at="end" className="tip">
        <dl className="grid grid-cols-[auto_1fr] gap-x-2.5 gap-y-1">
          {rows.map(([k, v]) => (
            <span key={k} className="contents">
              <dt className="font-semibold whitespace-nowrap opacity-75">{k}</dt>
              <dd>{v}</dd>
            </span>
          ))}
        </dl>
      </span>
    </span>
  );
}

/** One product behind the finding: its picture (the shop's own, hotlinked), brand, name, price. */
function Product({ e, names }: { e: Example; names: Namers }) {
  const t = useTranslations('insights.findings');
  const locale = useLocale();
  const price =
    e.priceWithheld || !e.price ? t('priceWithheld') : moneyText(e.price.amount, e.price.currency, locale);
  return (
    <li className="min-w-0">
      <Link
        href={productHref(locale, e.id)}
        className="group flex min-w-0 flex-col gap-0.5 text-xs leading-snug"
      >
        <RowThumb
          url={e.image}
          label={`${e.brand} ${e.name}`}
          monogram={monogram(e.brand)}
          retailer={e.retailer}
          px={96}
          cls="relative aspect-square w-full overflow-hidden rounded-md bg-surface-2 object-contain"
        />
        <span className="mt-1 flex min-w-0 items-center gap-1.5 font-semibold">
          <RetailerDot id={e.retailer} />
          <span className="truncate" dir="auto">
            {e.brand}
          </span>
        </span>
        <span className="line-clamp-2 text-ink group-hover:underline" dir="auto">
          {e.name}
        </span>
        <span className="text-ink-2 tabular-nums">
          <bdi>{price}</bdi>
        </span>
        {e.versus && e.versusPrice && e.versus !== e.retailer && (
          <span className="text-ink-2">
            {names.shop(e.versus)}:{' '}
            <bdi className="tabular-nums">
              {moneyText(e.versusPrice.amount, e.versusPrice.currency, locale)}
            </bdi>
          </span>
        )}
      </Link>
    </li>
  );
}
