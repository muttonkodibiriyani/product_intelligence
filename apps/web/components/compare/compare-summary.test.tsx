import { cleanup, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { golden } from '@/lib/api/golden';
import type { Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { CompareRows } from './compare-rows';
import { Summary } from './compare-summary';

const compare = (golden('compare') as { data: Schemas['Comparison'] }).data;
const name = (id: string) => ({ shop_a: 'Shop A', shop_b: 'Shop B' })[id] ?? id;

afterEach(cleanup);

describe('Summary without a served summary', () => {
  it('says the summary is missing, not the products, while the matched rows still show below', () => {
    const data = structuredClone(compare);
    data.summary = null;
    data.rows = data.rows.slice(0, 3);
    data.total = 3;
    render(
      <NextIntlClientProvider locale="en" messages={en} onError={() => {}}>
        <Summary data={data} cohort={null} name={name} />
        <CompareRows data={data} name={name} from="x" />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText('Too few matched products for a summary yet.')).toBeTruthy();
    expect(screen.queryByText(/no matched products/i)).toBeNull();
    // The three counted rows are on screen, with the first product named.
    expect(screen.getAllByRole('row').length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(data.rows[0]!.name)).toBeTruthy();
    // No headline number is invented for the missing summary.
    expect(screen.queryByText('Products compared')).toBeNull();
  });
});
