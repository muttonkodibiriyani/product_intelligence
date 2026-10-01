'use client';

import { useEffect, useRef } from 'react';
import type { EChartsCoreOption, ECharts } from 'echarts/core';

/** The theme's CSS variables, read once per chart so the charts follow the tokens in globals.css. */
export type Palette = Record<
  | 'font'
  | 'ink'
  | 'ink2'
  | 'line'
  | 'line2'
  | 'line3'
  | 'surface'
  | 'surface2'
  | 'a'
  | 'b'
  | 'lav'
  | 'lavInk'
  | 'mint'
  | 'mintInk'
  | 'rose'
  | 'roseInk'
  | 'sky'
  | 'skyInk'
  | 'butter'
  | 'blush'
  | 'blushInk',
  string
>;

const VARS: Record<Exclude<keyof Palette, 'font'>, string> = {
  ink: '--color-ink',
  ink2: '--color-ink-2',
  line: '--color-line',
  line2: '--color-line-2',
  line3: '--color-line-3',
  surface: '--color-surface',
  surface2: '--color-surface-2',
  a: '--color-series-a',
  b: '--color-series-b',
  lav: '--color-lav',
  lavInk: '--color-lav-ink',
  mint: '--color-mint',
  mintInk: '--color-mint-ink',
  rose: '--color-rose',
  roseInk: '--color-rose-ink',
  sky: '--color-sky',
  skyInk: '--color-sky-ink',
  butter: '--color-butter',
  blush: '--color-blush',
  blushInk: '--color-blush-ink',
};

export function palette(): Palette {
  const css = getComputedStyle(document.documentElement);
  return {
    ...Object.fromEntries(
      Object.entries(VARS).map(([k, v]) => [k, css.getPropertyValue(v).trim() || '#888']),
    ),
    // The resolved stack, not 'inherit': ECharts measures labels with it to size the grid.
    font: getComputedStyle(document.body).fontFamily || 'system-ui, sans-serif',
  } as Palette;
}

/** Shared look: system font, muted axes, a white tooltip card, motion only when welcome. */
export function base(p: Palette, rtl: boolean): EChartsCoreOption {
  return {
    textStyle: { fontFamily: p.font, color: p.ink2, fontSize: 12 },
    // No motion for a reader who asked for none (WCAG 2.3.3).
    animation: !globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
    animationDuration: 300,
    aria: { enabled: true },
    tooltip: {
      backgroundColor: p.surface,
      borderColor: p.line,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { fontFamily: p.font, color: p.ink, fontSize: 13 },
      extraCssText: `box-shadow:0 12px 32px rgb(29 33 48 / .10);border-radius:10px;direction:${rtl ? 'rtl' : 'ltr'};text-align:start`,
      confine: true,
    },
  };
}

/** The widest of some labels in the chart font, in px, for a gutter ECharts doesn't have to guess. */
export function labelWidth(labels: string[], p: Palette, size = 12): number {
  const ctx = document.createElement('canvas').getContext('2d');
  if (!ctx) return 120;
  ctx.font = `${size}px ${p.font}`;
  return Math.ceil(Math.max(0, ...labels.map((l) => ctx.measureText(l).width)));
}

type Loaded = typeof import('echarts/core');
let loading: Promise<Loaded> | null = null;

/** ECharts, tree-shaken to the charts the dashboard uses, SVG only, loaded on first use. */
function load(): Promise<Loaded> {
  loading ??= Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ]).then(([core, charts, comps, renderers]) => {
    core.use([
      charts.BarChart,
      charts.LineChart,
      charts.CustomChart,
      charts.BoxplotChart,
      charts.HeatmapChart,
      charts.ScatterChart,
      charts.TreemapChart,
      comps.GridComponent,
      comps.LegendComponent,
      comps.MarkLineComponent,
      comps.TooltipComponent,
      comps.VisualMapComponent,
      comps.AriaComponent,
      renderers.SVGRenderer,
    ]);
    return core;
  });
  return loading;
}

/**
 * One chart. `build` turns the palette into options; it reruns when `deps` change. `onPick`
 * receives the clicked datum's name, so a mark can drill into the list behind it.
 */
type Formatter = (...a: unknown[]) => unknown;

/**
 * Tooltip formatters read the fields their widget's marks carry. A mark without them (a treemap
 * root, a marker) shows no tooltip instead of throwing.
 */
export function guarded(o: EChartsCoreOption): EChartsCoreOption {
  const wrap = (t: unknown) => {
    const f = (t as { formatter?: unknown } | undefined)?.formatter;
    if (typeof f !== 'function') return;
    (t as { formatter: Formatter }).formatter = (...a) => {
      try {
        return (f as Formatter)(...a);
      } catch {
        return '';
      }
    };
  };
  for (const t of [o.tooltip].flat()) wrap(t);
  for (const s of [o.series].flat()) wrap((s as { tooltip?: unknown } | undefined)?.tooltip);
  return o;
}

export function Chart({
  build,
  deps,
  height = 280,
  label,
  onPick,
}: {
  build: (p: Palette) => EChartsCoreOption;
  deps: readonly unknown[];
  height?: number;
  label: string;
  onPick?: (name: string, data: unknown) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const pick = useRef(onPick);
  useEffect(() => {
    pick.current = onPick;
  });

  useEffect(() => {
    let gone = false;
    let ro: ResizeObserver | null = null;
    void load().then((echarts) => {
      if (gone || !el.current) return;
      const c = echarts.init(el.current, null, { renderer: 'svg' });
      chart.current = c;
      c.setOption(guarded(build(palette())));
      c.on('click', (e) => {
        try {
          pick.current?.(String(e.name ?? ''), e.data);
        } catch {
          // A mark the widget does not drill from (a treemap root, a marker): no drill.
        }
      });
      ro = new ResizeObserver(() => c.resize());
      ro.observe(el.current);
    });
    return () => {
      gone = true;
      ro?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
    // Rebuilt from scratch when the data changes: the charts are small.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // LTR box: an inherited rtl direction flips SVG text-anchor and misplaces axis labels. The
  // options mirror the layout for Arabic instead, and the tooltip sets its own direction.
  return (
    <div ref={el} dir="ltr" role="img" aria-label={label} data-chart className="w-full" style={{ height }} />
  );
}
