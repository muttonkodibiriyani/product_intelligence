'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import type { Bucket } from '@/lib/api/category-compare';
import type { Measured } from '@/lib/api/summary';
import { num } from '@/lib/api/summary';
import type { Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import type { GroupBy } from '@/lib/compare';
import { productHref } from '../explore/product-table';
import { base, Chart, labelWidth, type Palette } from './chart';
import { BRANDS_TOP, CROSS_COLS, CROSS_ROWS, MIN_PAIRS, SHARE_TOP } from './constants';
import {
  amount,
  bandFloor,
  brandShare,
  categoryNodeHref,
  categoryNodes,
  cheaperCells,
  compareHref,
  exploreHref,
  gapRows,
  heatCells,
  histBins,
  ladderRows,
  pct,
  promotionsHref,
  ratingPoints,
  trendPoints,
  type TreeNode,
  cheaperShares,
  crossCells,
  type CrossCell,
} from './model';

/*
 * The landing's charts. Each takes its slice of /summary, the currency and the locale; each mark
 * opens the products it counts (explore or promotions), so a number is two clicks from evidence.
 * In Arabic the value axis runs right to left and labels sit on the right.
 */

interface Props<T> {
  data: T;
  currency: string;
  locale: string;
  height?: number;
  /**
   * Opens a mark's drill. Without it the widget navigates this tab; the assistant passes its own
   * (a new tab, so the thread stays). `href` is locale-prefixed and has no basePath.
   */
  onPick?: (href: string) => void;
}

/** Where a mark's drill goes: the caller's `onPick` when given, else this tab. */
function useDrill(onPick?: (href: string) => void) {
  const router = useRouter();
  return (href: string) => (onPick ? onPick(href) : router.push(href));
}

/** Escapes text going into an HTML tooltip: category and brand names come from the retailer. */
const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

const tipRow = (label: string, value: string) =>
  `<div style="display:flex;gap:16px;justify-content:space-between"><span>${esc(label)}</span><b style="font-weight:600">${esc(value)}</b></div>`;

const tipLine = (s: string) => `<div>${esc(s)}</div>`;

const tipHead = (s: string) => `<div style="font-weight:600;margin-bottom:4px">${esc(s)}</div>`;

/** Price-axis end labels grow inward: centred, ECharts shrinks a narrow grid to fit them, to nothing on a phone. */
const edgeLabels = (rtl: boolean) =>
  ({ alignMinLabel: rtl ? 'right' : 'left', alignMaxLabel: rtl ? 'left' : 'right' }) as const;

const axisLine = (p: Palette) => ({ lineStyle: { color: p.line } });
const splitLine = (p: Palette) => ({ lineStyle: { color: p.line2 } });

/** Truncates long axis labels; the tooltip has the full name. */
const short = (s: string, n = 18) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export function LadderWidget({ data, currency, locale, height, onPick }: Props<Measured<'ladder'>>) {
  const t = useTranslations('widgets.ladder');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rows = ladderRows(data);
  const rtl = locale === 'ar';
  const h = height ?? Math.max(220, rows.length * 34 + 60);
  return (
    <>
      <Legend
        items={[
          { label: t('entry'), color: 'bg-mint' },
          { label: t('mid'), color: 'bg-lav' },
          { label: t('premium'), color: 'bg-blush' },
        ]}
        median={t('median')}
      />
      <Chart
        label={t('label', { n: rows.length })}
        height={h}
        deps={[data, locale, currency]}
        onPick={(name) => name && drill(exploreHref(locale, { category: [name] }))}
        build={(p) => {
          const bands = [p.mint, p.lav, p.blush];
          // A measured gutter for the category names: ECharts 6's own fit collapses this grid on
          // a phone in Arabic (the log axis shrinks to zero width).
          const gutter =
            labelWidth(
              rows.map((r) => short(r.category, 22)),
              p,
            ) + 16;
          return {
            ...base(p, rtl),
            grid: {
              left: rtl ? 28 : gutter,
              right: rtl ? gutter : 28,
              top: 8,
              bottom: 28,
              outerBoundsMode: 'none',
            },
            xAxis: {
              type: 'log',
              inverse: rtl,
              // Bounded to the data, so the log scale doesn't run out to the next power of ten.
              min: Math.min(...rows.map((r) => r.v[0])) * 0.8,
              max: Math.max(...rows.map((r) => r.v[4])) * 1.25,
              axisLine: axisLine(p),
              splitLine: splitLine(p),
              axisLabel: {
                formatter: (v: number) => amount(String(v), currency, locale, true),
                hideOverlap: true,
                ...edgeLabels(rtl),
              },
            },
            yAxis: {
              type: 'category',
              inverse: true,
              position: rtl ? 'right' : 'left',
              data: rows.map((r) => r.category),
              axisTick: { show: false },
              axisLine: axisLine(p),
              axisLabel: { color: p.ink, formatter: (v: string) => short(v, 22) },
            },
            tooltip: {
              ...(base(p, rtl).tooltip as object),
              trigger: 'item',
              formatter: (e: { dataIndex: number }) => {
                const r = rows[e.dataIndex]!;
                const m = (v: { amount: string }) => amount(v.amount, currency, locale);
                return (
                  tipHead(r.category) +
                  tipLine(tw('products', { n: r.n })) +
                  tipRow(t('entry'), `${m(r.min)} – ${m(r.p25)}`) +
                  tipRow(t('mid'), `${m(r.p25)} – ${m(r.p75)}`) +
                  tipRow(t('premium'), `${m(r.p75)} – ${m(r.max)}`) +
                  tipRow(t('median'), m(r.p50))
                );
              },
            },
            series: [
              {
                type: 'custom',
                name: t('title'),
                encode: { x: [1, 2, 3, 4, 5], y: 0 },
                data: rows.map((r, i) => ({ name: r.category, value: [i, ...r.v] })),
                renderItem: (
                  params: { coordSys: { x: number; width: number } },
                  api: {
                    value: (d: number) => number;
                    coord: (v: [number, number]) => [number, number];
                    size: (v: [number, number]) => [number, number];
                  },
                ) => {
                  const y = api.value(0);
                  const [min, p25, p50, p75, max] = [1, 2, 3, 4, 5].map((d) => api.value(d)) as [
                    number,
                    number,
                    number,
                    number,
                    number,
                  ];
                  const bh = Math.min(18, api.size([0, 1])[1] * 0.6);
                  const seg = (a: number, b: number, fill: string) => {
                    const [x0, cy] = api.coord([a, y]);
                    const [x1] = api.coord([b, y]);
                    return {
                      type: 'rect',
                      shape: {
                        x: Math.min(x0, x1),
                        y: cy - bh / 2,
                        width: Math.max(2, Math.abs(x1 - x0)),
                        height: bh,
                      },
                      style: { fill },
                    };
                  };
                  const [mx, my] = api.coord([p50, y]);
                  const rowH = api.size([0, 1])[1];
                  return {
                    type: 'group',
                    children: [
                      // The whole row is the target, so a click anywhere on it opens the category.
                      {
                        type: 'rect',
                        shape: {
                          x: params.coordSys.x,
                          y: my - rowH / 2,
                          width: params.coordSys.width,
                          height: rowH,
                        },
                        style: { fill: 'rgba(0,0,0,0)' },
                      },
                      seg(min, p25, bands[0]!),
                      seg(p25, p75, bands[1]!),
                      seg(p75, max, bands[2]!),
                      {
                        type: 'rect',
                        shape: { x: mx - 1.5, y: my - bh / 2 - 3, width: 3, height: bh + 6 },
                        style: { fill: p.ink },
                      },
                    ],
                  };
                },
              },
            ],
          };
        }}
      />
      <p className="mt-1 text-xs text-ink-2">{t('legend')}</p>
    </>
  );
}

export function PromoDepthWidget({ data, locale, height, onPick }: Props<Measured<'promoDepth'>>) {
  const t = useTranslations('widgets.promo');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const { cells, max } = heatCells(data);
  return (
    <Chart
      label={t('label')}
      height={height ?? Math.max(240, data.category.length * 30 + 70)}
      deps={[data, locale]}
      onPick={(_, d) => {
        const v = (d as [number, number, number] | undefined) ?? undefined;
        if (!v || !v[2]) return;
        drill(
          promotionsHref(locale, {
            category: data.category[v[1]],
            minPct: bandFloor(data.bands[v[0]] ?? ''),
          }),
        );
      }}
      build={(p) => ({
        ...base(p, rtl),
        grid: { left: rtl ? 8 : 8, right: 8, top: 8, bottom: 56, containLabel: true },
        xAxis: {
          type: 'category',
          inverse: rtl,
          data: data.bands,
          axisTick: { show: false },
          axisLine: axisLine(p),
          splitArea: { show: false },
          axisLabel: { color: p.ink },
        },
        yAxis: {
          type: 'category',
          inverse: true,
          position: rtl ? 'right' : 'left',
          data: data.category,
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: { color: p.ink, formatter: (v: string) => short(v, 22) },
        },
        visualMap: {
          min: 0,
          max: Math.max(max, 1),
          calculable: false,
          orient: 'horizontal',
          left: 'center',
          bottom: 0,
          itemHeight: 120,
          itemWidth: 10,
          inverse: rtl,
          // text[0] sits at the high end, which `inverse` moves to the left in Arabic.
          text: [t('more'), t('fewer')],
          textStyle: { color: p.ink2, fontSize: 11 },
          inRange: { color: [p.line2, p.blush, p.a] },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'item',
          formatter: (e: { data: [number, number, number] }) => {
            const [c, r, n] = e.data;
            return (
              tipHead(data.category[r] ?? '') +
              tipRow(t('off', { band: data.bands[c] ?? '' }), tw('products', { n }))
            );
          },
        },
        series: [
          {
            type: 'heatmap',
            name: t('title'),
            data: cells,
            itemStyle: { borderColor: p.surface, borderWidth: 2, borderRadius: 4 },
            label: {
              show: true,
              color: p.ink,
              fontSize: 11,
              formatter: (e: { data: [number, number, number] }) =>
                e.data[2] ? formatCount(e.data[2], locale) : '',
            },
            emphasis: { itemStyle: { borderColor: p.ink, borderWidth: 1 } },
          },
        ],
      })}
    />
  );
}

export function BrandPriceWidget({
  data,
  currency,
  locale,
  height,
  top = BRANDS_TOP,
  onPick,
}: Props<Measured<'brandPrice'>> & { top?: number }) {
  const t = useTranslations('widgets.brands');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  // The largest brands by products (as sent, n desc), ranked by median price.
  const rows = data
    .slice(0, top)
    .filter((b) => num(b.median.amount) > 0)
    .sort((a, b) => num(b.median.amount) - num(a.median.amount));
  return (
    <Chart
      label={t('label', { n: rows.length })}
      height={height ?? Math.max(240, rows.length * 24 + 40)}
      deps={[data, locale, currency]}
      onPick={(name) => name && drill(exploreHref(locale, { brand: [name] }))}
      build={(p) => ({
        ...base(p, rtl),
        grid: { left: 8, right: 16, top: 4, bottom: 24, containLabel: true },
        xAxis: {
          type: 'value',
          inverse: rtl,
          axisLine: axisLine(p),
          splitLine: splitLine(p),
          axisLabel: {
            formatter: (v: number) => amount(String(v), currency, locale, true),
            hideOverlap: true,
            ...edgeLabels(rtl),
          },
        },
        yAxis: {
          type: 'category',
          inverse: true,
          position: rtl ? 'right' : 'left',
          data: rows.map((r) => r.brand),
          axisTick: { show: false },
          axisLine: axisLine(p),
          axisLabel: { color: p.ink, formatter: (v: string) => short(v, 20) },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'item',
          formatter: (e: { dataIndex: number }) => {
            const r = rows[e.dataIndex]!;
            return (
              tipHead(r.brand) +
              tipRow(tw('ladder.median'), amount(r.median.amount, currency, locale)) +
              tipLine(tw('products', { n: r.n }))
            );
          },
        },
        series: [
          {
            type: 'bar',
            name: t('title'),
            data: rows.map((r) => ({ name: r.brand, value: num(r.median.amount) })),
            barMaxWidth: 14,
            itemStyle: { color: p.a, borderRadius: rtl ? [4, 0, 0, 4] : [0, 4, 4, 0] },
            emphasis: { itemStyle: { color: p.blushInk } },
          },
        ],
      })}
    />
  );
}

export function BrandShareWidget({
  data,
  priced,
  locale,
  height,
  onPick,
}: Props<Measured<'brandPrice'>> & { priced: number }) {
  const t = useTranslations('widgets.share');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const rows = brandShare(data, priced).slice(0, SHARE_TOP);
  const share = (v: number) => pct(v.toFixed(1), locale);
  const last = rows[rows.length - 1];
  return (
    <>
      {last && (
        <p className="mb-2 text-sm">
          {t.rich('headline', {
            k: rows.length,
            share: share(last.cum),
            b: (c) => <b className="font-semibold tabular-nums">{c}</b>,
          })}
        </p>
      )}
      <Chart
        label={t('label', { n: rows.length })}
        height={height ?? Math.max(240, rows.length * 24 + 40)}
        deps={[data, priced, locale]}
        onPick={(name) => name && drill(exploreHref(locale, { brand: [name] }))}
        build={(p) => ({
          ...base(p, rtl),
          grid: { left: 8, right: 16, top: 4, bottom: 24, containLabel: true },
          xAxis: {
            type: 'value',
            inverse: rtl,
            axisLine: axisLine(p),
            splitLine: splitLine(p),
            axisLabel: { formatter: (v: number) => share(v), hideOverlap: true },
          },
          yAxis: {
            type: 'category',
            inverse: true,
            position: rtl ? 'right' : 'left',
            data: rows.map((r) => r.brand),
            axisTick: { show: false },
            axisLine: axisLine(p),
            axisLabel: { color: p.ink, formatter: (v: string) => short(v, 20) },
          },
          tooltip: {
            ...(base(p, rtl).tooltip as object),
            trigger: 'item',
            formatter: (e: { dataIndex: number }) => {
              const r = rows[e.dataIndex]!;
              return (
                tipHead(r.brand) +
                tipRow(t('share'), share(r.share)) +
                tipRow(t('cum'), share(r.cum)) +
                tipLine(tw('products', { n: r.n }))
              );
            },
          },
          series: [
            {
              type: 'bar',
              name: t('title'),
              data: rows.map((r) => ({ name: r.brand, value: r.share })),
              barMaxWidth: 14,
              itemStyle: { color: p.b, borderRadius: rtl ? [4, 0, 0, 4] : [0, 4, 4, 0] },
              emphasis: { itemStyle: { color: p.skyInk } },
            },
          ],
        })}
      />
    </>
  );
}

export function CategoryMixWidget({ data, locale, height, onPick }: Props<Measured<'categoryMix'>>) {
  const t = useTranslations('widgets.mix');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const tree = categoryNodes(data);
  return (
    <Chart
      label={t('label', { n: tree.length })}
      height={height ?? 320}
      deps={[data, locale]}
      onPick={(_, d) => {
        const node = d as TreeNode | undefined;
        if (node?.trail?.length) drill(categoryNodeHref(locale, node));
      }}
      build={(p) => {
        const colors = [p.lav, p.mint, p.sky, p.blush, p.butter, p.rose];
        return {
          ...base(p, rtl),
          tooltip: {
            ...(base(p, rtl).tooltip as object),
            formatter: (e: { data?: Partial<TreeNode> }) =>
              e.data?.trail
                ? tipHead(e.data.trail.join(' › ')) + tipLine(tw('products', { n: e.data.value ?? 0 }))
                : '',
          },
          series: [
            {
              type: 'treemap',
              name: t('title'),
              data: tree.map((n, i) => ({ ...n, itemStyle: { color: colors[i % colors.length] } })),
              roam: false,
              nodeClick: false,
              breadcrumb: { show: false },
              leafDepth: 1,
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              label: {
                color: p.ink,
                fontSize: 12,
                overflow: 'truncate',
                formatter: (e: { name: string; value: number }) =>
                  `${e.name}\n${formatCount(e.value, locale)}`,
              },
              itemStyle: { borderColor: p.surface, borderWidth: 2, gapWidth: 2, borderRadius: 6 },
              levels: [{ itemStyle: { borderColor: p.surface, borderWidth: 3, gapWidth: 3 } }],
            },
          ],
        };
      }}
    />
  );
}

export function PriceHistWidget({ data, currency, locale, height, onPick }: Props<Measured<'priceHist'>>) {
  const t = useTranslations('widgets.hist');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const bins = histBins(data);
  const label = (b: { lo: string; hi: string }) =>
    `${amount(b.lo, currency, locale, true)} – ${amount(b.hi, currency, locale, true)}`;
  return (
    <Chart
      label={t('label', { n: bins.length })}
      height={height ?? 260}
      deps={[data, locale, currency]}
      onPick={(_, d) => {
        const b = bins[(d as { idx?: number } | undefined)?.idx ?? -1];
        if (b) drill(exploreHref(locale, { priceMin: b.lo, priceMax: b.hi, sort: 'price_asc' }));
      }}
      build={(p) => ({
        ...base(p, rtl),
        grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
        xAxis: {
          type: 'category',
          inverse: rtl,
          data: bins.map((b) => amount(b.lo, currency, locale, true)),
          axisTick: { show: false },
          axisLine: axisLine(p),
          axisLabel: { hideOverlap: true },
        },
        yAxis: {
          type: 'value',
          position: rtl ? 'right' : 'left',
          splitLine: splitLine(p),
          axisLabel: { formatter: (v: number) => formatCount(v, locale) },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'item',
          formatter: (e: { dataIndex: number }) => {
            const b = bins[e.dataIndex]!;
            return tipHead(label(b)) + tipLine(tw('products', { n: b.count }));
          },
        },
        series: [
          {
            type: 'bar',
            name: t('title'),
            data: bins.map((b, idx) => ({ value: b.count, idx })),
            barCategoryGap: '8%',
            itemStyle: { color: p.b, borderRadius: [4, 4, 0, 0] },
            emphasis: { itemStyle: { color: p.skyInk } },
          },
        ],
      })}
    />
  );
}

export function RatingPriceWidget({ data, currency, locale, height }: Props<Measured<'ratingPrice'>>) {
  const t = useTranslations('widgets.rating');
  const rtl = locale === 'ar';
  const pts = ratingPoints(data);
  const maxReviews = Math.max(1, ...pts.map((x) => x[2]));
  return (
    <Chart
      label={t('label', { k: pts.length })}
      height={height ?? 280}
      deps={[data, locale, currency]}
      build={(p) => ({
        ...base(p, rtl),
        grid: { left: 8, right: 16, top: 28, bottom: 30, containLabel: true },
        xAxis: {
          type: 'log',
          name: t('price'),
          nameLocation: 'middle',
          nameGap: 26,
          inverse: rtl,
          axisLine: axisLine(p),
          splitLine: splitLine(p),
          axisLabel: {
            formatter: (v: number) => amount(String(v), currency, locale, true),
            hideOverlap: true,
            ...edgeLabels(rtl),
          },
        },
        yAxis: {
          type: 'value',
          name: t('rating'),
          position: rtl ? 'right' : 'left',
          min: 0,
          max: Number(data.scale) > 0 ? Number(data.scale) : 5,
          interval: 1,
          splitLine: splitLine(p),
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'item',
          formatter: (e: { data: [number, number, number] }) =>
            tipRow(t('price'), amount(String(e.data[0]), currency, locale)) +
            tipRow(t('rating'), e.data[1].toFixed(1)) +
            tipLine(t('reviews', { n: e.data[2] })),
        },
        series: [
          {
            type: 'scatter',
            name: t('title'),
            data: pts,
            symbolSize: (v: [number, number, number]) => 5 + 13 * Math.sqrt(v[2] / maxReviews),
            itemStyle: { color: p.a, opacity: 0.55, borderColor: p.blushInk, borderWidth: 0.5 },
          },
        ],
      })}
    />
  );
}

/*
 * Head-to-head widgets. They draw /compare and /index for one pair, on the MATCHED set only: the
 * caller shows the comparable-pair count next to each one. Positive gaps mean `other` is dearer
 * (the API's convention); the bars take the dearer retailer's colour.
 */

type Pair = { base: string; other: string; name: (id: string) => string };

/** Gap bars run from zero both ways; positive is `other` dearer. */
const gapColor = (p: Palette, v: number) => (v > 0 ? p.a : v < 0 ? p.b : p.line);

const signedPct = (v: string, locale: string) => {
  const n = num(v);
  return `${n > 0 ? '+' : ''}${pct(v, locale)}`;
};

export function IndexTrendWidget({
  data,
  locale,
  height,
  pair,
}: Props<Schemas['PriceIndex']> & { pair: Pair }) {
  const t = useTranslations('widgets.index');
  const tw = useTranslations('widgets');
  const rtl = locale === 'ar';
  const pts = trendPoints(data);
  // Owner rule: no line over time until real multi-day history exists.
  if (!pts) return <p className="text-sm text-ink-2">{t('noHistory')}</p>;
  const vals = pts.map((p) => num(p.index));
  const pad = Math.max(2, (Math.max(...vals) - Math.min(...vals)) * 0.5);
  return (
    <Chart
      label={t('label', { n: pts.length })}
      height={height ?? 240}
      deps={[data, locale]}
      build={(p) => ({
        ...base(p, rtl),
        grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
        xAxis: {
          type: 'category',
          inverse: rtl,
          boundaryGap: false,
          data: pts.map((x) => formatDate(x.date, locale)),
          axisTick: { show: false },
          axisLine: axisLine(p),
        },
        yAxis: {
          type: 'value',
          position: rtl ? 'right' : 'left',
          min: Math.floor(Math.min(100, ...vals) - pad),
          max: Math.ceil(Math.max(100, ...vals) + pad),
          splitLine: splitLine(p),
          axisLabel: { formatter: (v: number) => formatCount(v, locale) },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'axis',
          formatter: (e: { dataIndex: number }[]) => {
            const x = pts[e[0]!.dataIndex]!;
            return (
              tipHead(formatDate(x.date, locale)) +
              tipRow(
                `${t('index')} · ${pair.name(pair.other)} / ${pair.name(pair.base)}`,
                formatCount(num(x.index), locale),
              ) +
              tipLine(tw('pairs', { n: x.n }))
            );
          },
        },
        series: [
          {
            type: 'line',
            name: t('title'),
            data: vals,
            smooth: false,
            symbol: 'circle',
            symbolSize: 7,
            lineStyle: { width: 2, color: p.lavInk },
            itemStyle: { color: p.lavInk, borderColor: p.surface, borderWidth: 2 },
            areaStyle: { color: p.lav, opacity: 0.6 },
            markLine: {
              symbol: 'none',
              silent: true,
              lineStyle: { color: p.ink2, type: 'dashed', width: 1 },
              label: { color: p.ink2, formatter: t('parity'), position: rtl ? 'start' : 'end' },
              data: [{ yAxis: 100 }],
            },
          },
        ],
      })}
    />
  );
}

export function TopGapsWidget({
  data,
  currency,
  locale,
  height,
  pair,
  top = 10,
  onPick,
}: Props<readonly Schemas['PairRow'][]> & { pair: Pair; top?: number }) {
  const t = useTranslations('widgets.gaps');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const rows = gapRows(data, top);
  const h = height ?? Math.max(200, rows.length * 28 + 48);
  return (
    <Chart
      label={t('label', { n: rows.length })}
      height={h}
      deps={[data, locale, currency, top]}
      onPick={(_, d) => {
        const id = (d as { id?: string } | undefined)?.id;
        if (id) drill(productHref(locale, id));
      }}
      build={(p) => {
        const gutter =
          labelWidth(
            rows.map((r) => short(r.name, 26)),
            p,
          ) + 12;
        // The value labels sit at each bar's outer end, so the grid leaves room for them past the
        // longest bar on each side the data reaches; mirrored in Arabic.
        const valW =
          labelWidth(
            rows.map((r) => signedPct(r.gap.pct, locale)),
            p,
            11,
          ) + 8;
        const pos = rows.some((r) => num(r.gap.pct) > 0) ? valW : 16;
        const neg = rows.some((r) => num(r.gap.pct) < 0) ? valW : 0;
        return {
          ...base(p, rtl),
          grid: {
            left: rtl ? pos : gutter + neg,
            right: rtl ? gutter + neg : pos,
            top: 4,
            bottom: 24,
            outerBoundsMode: 'none',
          },
          xAxis: {
            type: 'value',
            inverse: rtl,
            axisLine: axisLine(p),
            splitLine: splitLine(p),
            axisLabel: { formatter: (v: number) => signedPct(String(v), locale), hideOverlap: true },
          },
          yAxis: {
            type: 'category',
            inverse: true,
            position: rtl ? 'right' : 'left',
            data: rows.map((r) => r.name),
            axisTick: { show: false },
            axisLine: { show: false },
            axisLabel: { color: p.ink, formatter: (v: string) => short(v, 26) },
          },
          tooltip: {
            ...(base(p, rtl).tooltip as object),
            trigger: 'item',
            formatter: (e: { dataIndex: number }) => {
              const r = rows[e.dataIndex]!;
              return (
                tipHead(r.name) +
                tipLine(r.brand) +
                tipRow(pair.name(pair.base), amount(r.basePrice!.amount, currency, locale)) +
                tipRow(pair.name(pair.other), amount(r.otherPrice!.amount, currency, locale)) +
                tipRow(
                  t('gap'),
                  `${amount(r.gap.amount.amount, currency, locale)} · ${signedPct(r.gap.pct, locale)}`,
                )
              );
            },
          },
          series: [
            {
              type: 'bar',
              name: t('title'),
              data: rows.map((r) => ({
                id: r.id,
                name: r.name,
                value: num(r.gap.pct),
                itemStyle: { color: gapColor(p, num(r.gap.pct)) },
                // Outer end of the bar: past zero on the side the bar runs to.
                label: { position: num(r.gap.pct) < 0 ? (rtl ? 'right' : 'left') : rtl ? 'left' : 'right' },
              })),
              barMaxWidth: 14,
              itemStyle: { borderRadius: 3 },
              emphasis: { itemStyle: { color: p.ink } },
              label: {
                show: true,
                color: p.ink2,
                fontSize: 11,
                position: rtl ? 'left' : 'right',
                formatter: (e: { value: number }) => signedPct(String(e.value), locale),
              },
            },
          ],
        };
      }}
    />
  );
}

export function CheaperHeatmapWidget({
  data,
  locale,
  height,
  pair,
  onPick,
}: Props<readonly Schemas['Group'][]> & { pair: Pair }) {
  const t = useTranslations('widgets.cheaper');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const { rows, thin, cells, max } = cheaperCells(data, pair.base, pair.other);
  const cols = [
    t('baseCheaper', { r: pair.name(pair.base) }),
    t('same'),
    t('otherCheaper', { r: pair.name(pair.other) }),
  ];
  return (
    <>
      <Chart
        label={t('label', { n: rows.length })}
        height={height ?? Math.max(120, rows.length * 30 + 76)}
        deps={[data, locale]}
        onPick={(_, d) => {
          const v = d as [number, number, number] | undefined;
          const g = v && rows[v[1]];
          if (g) drill(compareHref(locale, { ...pair, groupBy: 'category', category: g.key }));
        }}
        build={(p) => ({
          ...base(p, rtl),
          grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
          xAxis: {
            type: 'category',
            inverse: rtl,
            data: cols,
            axisTick: { show: false },
            axisLine: axisLine(p),
            axisLabel: { color: p.ink, interval: 0, formatter: (v: string) => short(v, 18) },
          },
          yAxis: {
            type: 'category',
            inverse: true,
            position: rtl ? 'right' : 'left',
            data: rows.map((g) => g.key),
            axisTick: { show: false },
            axisLine: { show: false },
            axisLabel: { color: p.ink, formatter: (v: string) => short(v, 22) },
          },
          visualMap: {
            min: 0,
            max: Math.max(max, 1),
            calculable: false,
            orient: 'horizontal',
            left: 'center',
            bottom: 0,
            itemHeight: 120,
            itemWidth: 10,
            inverse: rtl,
            text: [t('more'), t('fewer')],
            textStyle: { color: p.ink2, fontSize: 11 },
            inRange: { color: [p.line2, p.lav, p.lavInk] },
          },
          tooltip: {
            ...(base(p, rtl).tooltip as object),
            trigger: 'item',
            formatter: (e: { data: [number, number, number] }) => {
              const [c, r, n] = e.data;
              const g = rows[r]!;
              return (
                tipHead(g.key) +
                tipRow(cols[c]!, tw('pairs', { n })) +
                tipRow(t('median'), signedPct(g.summary!.medianGapPct, locale)) +
                tipLine(tw('pairs', { n: g.summary!.n }))
              );
            },
          },
          series: [
            {
              type: 'heatmap',
              name: t('title'),
              data: cells,
              itemStyle: { borderColor: p.surface, borderWidth: 2, borderRadius: 4 },
              label: {
                show: true,
                fontSize: 11,
                formatter: (e: { data: [number, number, number] }) =>
                  e.data[2] ? formatCount(e.data[2], locale) : '',
              },
              emphasis: { itemStyle: { borderColor: p.ink, borderWidth: 1 } },
            },
          ],
        })}
      />
      {thin.length > 0 && (
        <p className="mt-1 text-xs text-ink-2">
          {t('thin', { n: thin.length, list: thin.map((g) => g.key).join(', ') })}
        </p>
      )}
    </>
  );
}

export function GroupGapWidget({
  data,
  locale,
  height,
  pair,
  groupBy,
  onPick,
}: Props<readonly Schemas['Group'][]> & { pair: Pair; groupBy: GroupBy }) {
  const t = useTranslations('widgets.groupGap');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const rows = data
    .filter((g): g is Schemas['Group'] & { summary: Schemas['CompareSummary'] } => !!g.summary)
    .sort((a, b) => num(b.summary.medianGapPct) - num(a.summary.medianGapPct));
  return (
    <Chart
      label={t('label', { n: rows.length })}
      height={height ?? Math.max(200, rows.length * 26 + 48)}
      deps={[data, locale, groupBy]}
      onPick={(name) => name && drill(compareHref(locale, { ...pair, groupBy, [groupBy]: name }))}
      build={(p) => ({
        ...base(p, rtl),
        grid: { left: 8, right: 40, top: 4, bottom: 24, containLabel: true },
        xAxis: {
          type: 'value',
          inverse: rtl,
          axisLine: axisLine(p),
          splitLine: splitLine(p),
          axisLabel: { formatter: (v: number) => signedPct(String(v), locale), hideOverlap: true },
        },
        yAxis: {
          type: 'category',
          inverse: true,
          position: rtl ? 'right' : 'left',
          data: rows.map((g) => g.key),
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: { color: p.ink, formatter: (v: string) => short(v, 22) },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'item',
          formatter: (e: { dataIndex: number }) => {
            const g = rows[e.dataIndex]!;
            return (
              tipHead(g.key) +
              tipRow(t('median'), signedPct(g.summary.medianGapPct, locale)) +
              tipRow(t('mean'), signedPct(g.summary.meanGapPct, locale)) +
              tipLine(tw('pairs', { n: g.summary.n }))
            );
          },
        },
        series: [
          {
            type: 'bar',
            name: t('title'),
            data: rows.map((g) => ({
              name: g.key,
              value: num(g.summary.medianGapPct),
              itemStyle: { color: gapColor(p, num(g.summary.medianGapPct)) },
            })),
            barMaxWidth: 14,
            itemStyle: { borderRadius: 3 },
            emphasis: { itemStyle: { color: p.ink } },
            label: {
              show: true,
              color: p.ink2,
              fontSize: 11,
              position: rtl ? 'left' : 'right',
              formatter: (e: { value: number }) => signedPct(String(e.value), locale),
            },
          },
        ],
      })}
    />
  );
}

function Legend({ items, median }: { items: { label: string; color: string }[]; median: string }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span aria-hidden className={`inline-block size-2.5 rounded-sm ${i.color}`} />
          {i.label}
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="inline-block h-3 w-0.5 bg-ink" />
        {median}
      </li>
    </ul>
  );
}

/**
 * Who is cheaper per category (rows) and brand (columns), from every counted pair of an
 * untruncated /compare response. A cell under the cohort minimum is muted and reads "too few
 * pairs"; it never shows a result. Positive (base cheaper more often) takes the base colour.
 */
export function CrossHeatmapWidget({
  data,
  locale,
  height,
  pair,
  onPick,
}: Props<readonly Schemas['PairRow'][]> & { pair: Pair }) {
  const t = useTranslations('widgets.cross');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const { cats, brands, cells, thin } = crossCells(data, {
    min: MIN_PAIRS,
    maxRows: CROSS_ROWS,
    maxCols: CROSS_COLS,
  });
  const baseName = pair.name(pair.base);
  const otherName = pair.name(pair.other);
  const points = cells.map((c) => ({
    // A thin cell carries no result; its 0 only parks a transparent, unlabelled tile for the layout.
    value: [c.col, c.row, c.value ?? 0] as [number, number, number],
    cell: c,
    itemStyle: c.value === null ? { color: 'transparent', borderColor: 'transparent' } : undefined,
    label: c.value === null ? { show: false } : undefined,
  }));
  return (
    <>
      <Chart
        label={t('label', { rows: cats.length, cols: brands.length })}
        // Sized to the rows it has (one row stays a short strip, not a tall panel).
        height={height ?? Math.max(120, cats.length * 34 + 80)}
        deps={[data, locale]}
        onPick={(_, d) => {
          const c = (d as { cell?: CrossCell } | undefined)?.cell;
          if (!c) return;
          drill(compareHref(locale, { ...pair, category: cats[c.row], brand: brands[c.col] }));
        }}
        build={(p) => ({
          ...base(p, rtl),
          grid: { left: 8, right: 8, top: 8, bottom: 64, containLabel: true },
          xAxis: {
            type: 'category',
            inverse: rtl,
            data: brands,
            axisTick: { show: false },
            axisLine: axisLine(p),
            axisLabel: {
              color: p.ink,
              interval: 0,
              rotate: brands.length > 5 ? 30 : 0,
              formatter: (v: string) => short(v, 14),
            },
          },
          yAxis: {
            type: 'category',
            inverse: true,
            position: rtl ? 'right' : 'left',
            data: cats,
            axisTick: { show: false },
            axisLine: { show: false },
            axisLabel: { color: p.ink, formatter: (v: string) => short(v, 22) },
          },
          visualMap: {
            min: -1,
            max: 1,
            calculable: false,
            orient: 'horizontal',
            left: 'center',
            bottom: 0,
            itemHeight: 140,
            itemWidth: 10,
            inverse: rtl,
            // text[0] sits at the high end (base cheaper); `inverse` mirrors the bar in Arabic.
            text: [t('baseSide', { r: baseName }), t('otherSide', { r: otherName })],
            textStyle: { color: p.ink2, fontSize: 11 },
            inRange: { color: [p.b, p.line2, p.a] },
          },
          tooltip: {
            ...(base(p, rtl).tooltip as object),
            trigger: 'item',
            formatter: (e: { data: { cell: CrossCell } }) => {
              const c = e.data.cell;
              return (
                tipHead(`${cats[c.row] ?? ''} · ${brands[c.col] ?? ''}`) +
                tipLine(tw('pairs', { n: c.n })) +
                (c.value === null
                  ? tipLine(t('thin'))
                  : tipLine(
                      t('cell', {
                        base: baseName,
                        other: otherName,
                        b: formatCount(c.baseWins, locale),
                        s: formatCount(c.equal, locale),
                        o: formatCount(c.otherWins, locale),
                      }),
                    ))
              );
            },
          },
          series: [
            {
              type: 'heatmap',
              name: t('title'),
              data: points,
              itemStyle: { borderColor: p.surface, borderWidth: 2, borderRadius: 4 },
              label: {
                show: true,
                color: p.ink,
                fontSize: 11,
                formatter: (e: { data: { cell: CrossCell } }) => formatCount(e.data.cell.n, locale),
              },
              emphasis: { itemStyle: { borderColor: p.ink, borderWidth: 1 } },
            },
            {
              // The thin cells, drawn hatched-light so they read as "not computed", with their count.
              type: 'scatter',
              name: t('thin'),
              data: cells.filter((c) => c.value === null).map((c) => ({ value: [c.col, c.row], cell: c })),
              symbol: 'roundRect',
              symbolSize: 22,
              itemStyle: { color: p.surface2, borderColor: p.line3, borderWidth: 1, borderType: 'dashed' },
              label: {
                show: true,
                color: p.ink2,
                fontSize: 10,
                formatter: (e: { data: { cell: CrossCell } }) => formatCount(e.data.cell.n, locale),
              },
              tooltip: {
                formatter: (e: { data: { cell: CrossCell } }) =>
                  tipHead(`${cats[e.data.cell.row] ?? ''} · ${brands[e.data.cell.col] ?? ''}`) +
                  tipLine(tw('pairs', { n: e.data.cell.n })) +
                  tipLine(t('thin')),
              },
            },
          ],
        })}
      />
      {thin > 0 && <p className="mt-1 text-xs text-ink-2">{t('thinNote', { n: thin, min: MIN_PAIRS })}</p>}
    </>
  );
}

/**
 * The fallback when /compare is truncated: each server group's share of pairs won by each
 * retailer (base, same, other) as a stacked bar, with the group's pair count beside it.
 */
export function CheaperShareWidget({
  data,
  locale,
  height,
  pair,
  groupBy,
  onPick,
}: Props<readonly Schemas['Group'][]> & { pair: Pair; groupBy: GroupBy }) {
  const t = useTranslations('widgets.cheaperShare');
  const tw = useTranslations('widgets');
  const drill = useDrill(onPick);
  const rtl = locale === 'ar';
  const rows = cheaperShares(data, pair.base, pair.other);
  const share = (v: number) => pct((v * 100).toFixed(0), locale);
  const names = [pair.name(pair.base), t('same'), pair.name(pair.other)];
  return (
    <Chart
      label={t('label', { n: rows.length, by: t(groupBy === 'brand' ? 'byBrand' : 'byCategory') })}
      height={height ?? Math.max(200, rows.length * 28 + 56)}
      deps={[data, locale, groupBy]}
      onPick={(_, d) => {
        const key = (d as { key?: string } | undefined)?.key;
        if (key) drill(compareHref(locale, { ...pair, groupBy, [groupBy]: key }));
      }}
      build={(p) => ({
        ...base(p, rtl),
        legend: { bottom: 0, left: 'center', textStyle: { color: p.ink2 }, itemWidth: 12, itemHeight: 8 },
        grid: { left: 8, right: 16, top: 4, bottom: 36, containLabel: true },
        xAxis: {
          type: 'value',
          inverse: rtl,
          max: 1,
          axisLine: axisLine(p),
          splitLine: splitLine(p),
          axisLabel: { formatter: (v: number) => share(v), hideOverlap: true },
        },
        yAxis: {
          type: 'category',
          inverse: true,
          position: rtl ? 'right' : 'left',
          data: rows.map((r) => `${r.key}  (${formatCount(r.n, locale)})`),
          axisTick: { show: false },
          axisLine: { show: false },
          axisLabel: { color: p.ink, formatter: (v: string) => short(v, 28) },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
          formatter: (e: { dataIndex: number }[]) => {
            const r = rows[e[0]!.dataIndex]!;
            return (
              tipHead(r.key) +
              tipLine(tw('pairs', { n: r.n })) +
              tipRow(names[0]!, `${share(r.base)} (${formatCount(r.baseN, locale)})`) +
              tipRow(names[1]!, `${share(r.same)} (${formatCount(r.sameN, locale)})`) +
              tipRow(names[2]!, `${share(r.other)} (${formatCount(r.otherN, locale)})`)
            );
          },
        },
        series: (['base', 'same', 'other'] as const).map((k, i) => ({
          type: 'bar',
          stack: 'share',
          name: names[i]!,
          data: rows.map((r) => ({ value: r[k], key: r.key })),
          barMaxWidth: 16,
          itemStyle: { color: k === 'base' ? p.a : k === 'same' ? p.line3 : p.b },
          emphasis: { focus: 'series' },
        })),
      })}
    />
  );
}

/**
 * The category centrepiece's chart: the median gap per shared bucket, `other` against `base`,
 * over both full catalogues. Only buckets with a gap are drawn (the thin ones are listed under
 * the chart in words); bars run from zero both ways, coloured by the cheaper retailer and
 * labelled with the gap and both counts. There is no drill: Explore has no bucket filter.
 */
export function BucketGapWidget({
  data,
  currency,
  locale,
  height,
  pair,
  label,
}: Props<readonly Bucket[]> & { pair: Pair; label: (b: Bucket) => string }) {
  const t = useTranslations('widgets.buckets');
  const rtl = locale === 'ar';
  const rows = data.filter((b) => b.status === 'ok' && b.gapPct !== null);
  const h = height ?? Math.max(160, rows.length * 30 + 48);
  const names = { base: pair.name(pair.base), other: pair.name(pair.other) };
  const count = (b: Bucket) =>
    `n ${formatCount(b.sides[pair.base]?.n ?? 0, locale)} / ${formatCount(b.sides[pair.other]?.n ?? 0, locale)}`;
  const valueText = (b: Bucket) => `${signedPct(b.gapPct!, locale)} · ${count(b)}`;
  return (
    <Chart
      label={t('chartLabel', { ...names, n: rows.length })}
      height={h}
      deps={[data, locale, currency]}
      build={(p) => {
        const gutter = labelWidth(rows.map(label), p) + 12;
        const valW = labelWidth(rows.map(valueText), p, 11) + 8;
        const pos = rows.some((r) => num(r.gapPct!) > 0) ? valW : 16;
        const neg = rows.some((r) => num(r.gapPct!) < 0) ? valW : 0;
        return {
          ...base(p, rtl),
          grid: {
            left: rtl ? pos : gutter + neg,
            right: rtl ? gutter + neg : pos,
            top: 4,
            bottom: 24,
            outerBoundsMode: 'none',
          },
          xAxis: {
            type: 'value',
            inverse: rtl,
            axisLine: axisLine(p),
            splitLine: splitLine(p),
            axisLabel: { formatter: (v: number) => signedPct(String(v), locale), hideOverlap: true },
          },
          yAxis: {
            type: 'category',
            inverse: true,
            position: rtl ? 'right' : 'left',
            data: rows.map(label),
            axisTick: { show: false },
            axisLine: { show: false },
            axisLabel: { color: p.ink },
          },
          tooltip: {
            ...(base(p, rtl).tooltip as object),
            trigger: 'item',
            formatter: (e: { dataIndex: number }) => {
              const b = rows[e.dataIndex]!;
              const side = (id: string) => {
                const s = b.sides[id]!;
                return `${amount(s.median!.amount, currency, locale)} · n ${formatCount(s.n, locale)}`;
              };
              return (
                tipHead(label(b)) +
                tipRow(names.base, side(pair.base)) +
                tipRow(names.other, side(pair.other)) +
                tipRow(t('gap'), signedPct(b.gapPct!, locale))
              );
            },
          },
          series: [
            {
              type: 'bar',
              name: t('gap'),
              data: rows.map((b) => ({
                name: label(b),
                value: num(b.gapPct!),
                itemStyle: { color: gapColor(p, num(b.gapPct!)) },
                label: { position: num(b.gapPct!) < 0 ? (rtl ? 'right' : 'left') : rtl ? 'left' : 'right' },
              })),
              barMaxWidth: 14,
              itemStyle: { borderRadius: 3 },
              emphasis: { itemStyle: { color: p.ink } },
              label: {
                show: true,
                color: p.ink2,
                fontSize: 11,
                formatter: (e: { dataIndex: number }) => valueText(rows[e.dataIndex]!),
              },
            },
          ],
        };
      }}
    />
  );
}
