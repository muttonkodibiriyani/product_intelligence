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
  | 'surface'
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
  surface: '--color-surface',
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

/** Shared look: system font, muted axes, a white tooltip card. */
export function base(p: Palette, rtl: boolean): EChartsCoreOption {
  return {
    textStyle: { fontFamily: p.font, color: p.ink2, fontSize: 12 },
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
      charts.CustomChart,
      charts.BoxplotChart,
      charts.HeatmapChart,
      charts.ScatterChart,
      charts.TreemapChart,
      comps.GridComponent,
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
      c.setOption(build(palette()));
      c.on('click', (e) => pick.current?.(String(e.name ?? ''), e.data));
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

  return <div ref={el} role="img" aria-label={label} data-chart className="w-full" style={{ height }} />;
}
