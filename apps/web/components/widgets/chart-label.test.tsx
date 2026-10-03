import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Chart } from './chart';

// A stand-in ECharts: what matters here is which aria description each draw is given.
const drawn: string[] = [];
vi.mock('echarts/core', () => ({
  use: () => {},
  init: () => ({
    setOption: (o: { aria?: { label?: { description?: string } } }) =>
      drawn.push(o.aria?.label?.description ?? ''),
    on: () => {},
    resize: () => {},
    dispose: () => {},
  }),
}));

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(cleanup);

describe('Chart', () => {
  it('redraws with the new label when only the label changes, so the chart never reads stale text', async () => {
    const data = [1, 2, 3];
    const build = () => ({ series: [{ type: 'bar', data }] });
    const { rerender } = render(<Chart build={build} deps={[data]} label="Matched pairs, 11 bands." />);
    await waitFor(() => expect(drawn.at(-1)).toBe('Matched pairs, 11 bands.'));
    rerender(<Chart build={build} deps={[data]} label="الأزواج المطابقة، 11 نطاقات." />);
    await waitFor(() => expect(drawn.at(-1)).toBe('الأزواج المطابقة، 11 نطاقات.'));
  });
});
