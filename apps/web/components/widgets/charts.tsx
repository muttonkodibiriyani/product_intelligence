'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import type { Measured } from '@/lib/api/summary';
import { num } from '@/lib/api/summary';
import { formatCount } from '@/lib/format';
import { base, Chart, labelWidth, type Palette } from './chart';
import { BRANDS_TOP, SHARE_TOP } from './constants';
import {
  amount,
  bandFloor,
  brandShare,
  categoryNodeHref,
  categoryNodes,
  exploreHref,
  heatCells,
  histBins,
  ladderRows,
  pct,
  promotionsHref,
  ratingPoints,
  type TreeNode,
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

export function LadderWidget({ data, currency, locale, height }: Props<Measured<'ladder'>>) {
  const t = useTranslations('widgets.ladder');
  const tw = useTranslations('widgets');
  const router = useRouter();
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
        onPick={(name) => name && router.push(exploreHref(locale, { category: [name] }))}
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

export function PromoDepthWidget({ data, locale, height }: Props<Measured<'promoDepth'>>) {
  const t = useTranslations('widgets.promo');
  const tw = useTranslations('widgets');
  const router = useRouter();
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
        router.push(
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
          textStyle: { color: p.ink2 },
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

export function BrandPriceWidget({ data, currency, locale, height }: Props<Measured<'brandPrice'>>) {
  const t = useTranslations('widgets.brands');
  const tw = useTranslations('widgets');
  const router = useRouter();
  const rtl = locale === 'ar';
  // The largest brands by products (as sent, n desc), ranked by median price.
  const rows = data
    .slice(0, BRANDS_TOP)
    .filter((b) => num(b.median.amount) > 0)
    .sort((a, b) => num(b.median.amount) - num(a.median.amount));
  return (
    <Chart
      label={t('label', { n: rows.length })}
      height={height ?? Math.max(240, rows.length * 24 + 40)}
      deps={[data, locale, currency]}
      onPick={(name) => name && router.push(exploreHref(locale, { brand: [name] }))}
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
}: Props<Measured<'brandPrice'>> & { priced: number }) {
  const t = useTranslations('widgets.share');
  const tw = useTranslations('widgets');
  const router = useRouter();
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
        onPick={(name) => name && router.push(exploreHref(locale, { brand: [name] }))}
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

export function CategoryMixWidget({ data, locale, height }: Props<Measured<'categoryMix'>>) {
  const t = useTranslations('widgets.mix');
  const tw = useTranslations('widgets');
  const router = useRouter();
  const rtl = locale === 'ar';
  const tree = categoryNodes(data);
  return (
    <Chart
      label={t('label', { n: tree.length })}
      height={height ?? 320}
      deps={[data, locale]}
      onPick={(_, d) => {
        const node = d as TreeNode | undefined;
        if (node?.trail?.length) router.push(categoryNodeHref(locale, node));
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

export function PriceHistWidget({ data, currency, locale, height }: Props<Measured<'priceHist'>>) {
  const t = useTranslations('widgets.hist');
  const tw = useTranslations('widgets');
  const router = useRouter();
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
        if (b) router.push(exploreHref(locale, { priceMin: b.lo, priceMax: b.hi, sort: 'price_asc' }));
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
