'use client';

import { useTranslations } from 'next-intl';
import { formatDate } from '@/lib/format';
import { retailerColor } from '../ui/retailer-dot';
import { base, Chart, type Palette } from '../widgets/chart';

const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

export interface LaunchSeries {
  id: string;
  name: string;
  index: number;
  perDay: readonly { date: string; n: number }[];
}

/**
 * Launches per day over the window, one bar series per shop, drawn with the app's ECharts
 * wrapper (components/widgets/chart.tsx). Only shops whose list the API did not cut are drawn,
 * so every day's count is complete.
 */
export function LaunchChart({
  series,
  locale,
  height,
}: {
  series: readonly LaunchSeries[];
  locale: string;
  height?: number;
}) {
  const t = useTranslations('home.insights');
  const tw = useTranslations('widgets');
  const rtl = locale === 'ar';
  const days = series[0]?.perDay ?? [];
  const label = t('launchesLabel', { n: days.length });
  return (
    <Chart
      label={label}
      height={height ?? 220}
      deps={[series, locale]}
      build={(p: Palette) => ({
        ...base(p, rtl),
        // The legend sits above the plot with room kept for it, clear of the date labels below.
        grid: { left: 8, right: 8, top: series.length > 1 ? 36 : 12, bottom: 8, containLabel: true },
        legend: { top: 0, show: series.length > 1, textStyle: { color: p.ink2 } },
        xAxis: {
          type: 'category',
          inverse: rtl,
          data: days.map((d) => d.date),
          axisTick: { show: false },
          axisLine: { lineStyle: { color: p.line } },
          axisLabel: { formatter: (v: string) => formatDate(v, locale), hideOverlap: true },
        },
        yAxis: {
          type: 'value',
          position: rtl ? 'right' : 'left',
          minInterval: 1,
          splitLine: { lineStyle: { color: p.line2 } },
        },
        tooltip: {
          ...(base(p, rtl).tooltip as object),
          trigger: 'axis',
          formatter: (items: { seriesName: string; value: number; axisValue: string }[]) =>
            `<div class="tip-head">${esc(formatDate(items[0]?.axisValue ?? '', locale))}</div>` +
            items
              .map(
                (i) =>
                  `<div class="tip-row"><span>${esc(i.seriesName)}</span><b>${esc(tw('products', { n: i.value }))}</b></div>`,
              )
              .join(''),
        },
        series: series.map((s) => ({
          type: 'bar',
          name: s.name,
          stack: 'launches',
          data: s.perDay.map((d) => d.n),
          barMaxWidth: 12,
          itemStyle: { color: cssColor(retailerColor(s.id, s.index)) },
        })),
      })}
    />
  );
}

/** A `var(--color-x)` as its computed value: ECharts paints into SVG and cannot resolve a variable. */
function cssColor(v: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(v);
  if (!m || typeof document === 'undefined') return v;
  return getComputedStyle(document.documentElement).getPropertyValue(m[1]!).trim() || v;
}
