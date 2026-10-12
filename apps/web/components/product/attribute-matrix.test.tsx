import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AttributeMatrix, attributeValueText } from './attribute-matrix';

const api = vi.hoisted(() => ({ page: vi.fn() }));
vi.mock('../auth-provider', () => ({ useAuth: () => ({ api }) }));

afterEach(() => {
  cleanup();
  api.page.mockReset();
});

type State = Schemas['AttributeState'];

function slot(index: number, state: State = 'observed'): Schemas['AttributeSlot'] {
  const base: Schemas['AttributeSlot'] = {
    targetId: 'p01:product',
    definition: {
      key: `field_${String(index).padStart(3, '0')}`,
      group: 'identity',
      level: 'product',
      kind: 'text',
      declaredType: 'text',
      label: { en: `Field ${index}`, ar: `الحقل ${index}` },
      enumValues: [],
    },
    state,
    evidence: [],
    alternatives: [],
  };
  if (state === 'observed')
    return {
      ...base,
      value: { kind: 'text', text: `Value ${index}` },
      evidence: [
        {
          source: 'page',
          field: `attributes.field_${index}`,
          excerpt: index === 1 ? '<img src=x onerror=alert(1)>' : null,
          capturedAt: '2026-10-01T09:00:00Z',
        },
      ],
    };
  if (state === 'conflict')
    return {
      ...base,
      alternatives: [
        {
          value: { kind: 'text', text: 'A' },
          evidence: [{ source: 'page', field: 'a' }],
        },
        {
          value: { kind: 'text', text: 'B' },
          evidence: [{ source: 'page', field: 'b' }],
        },
      ],
      reason: { en: 'Conflict', ar: 'متعارض' },
    };
  if (state === 'invalid')
    return {
      ...base,
      rawValue: 'bad',
      reason: { en: 'Invalid', ar: 'غير صالح' },
      evidence: [{ source: 'page', field: 'invalid' }],
    };
  return { ...base, reason: { en: state, ar: state } };
}

function answer(items: Schemas['AttributeSlot'][], nextCursor: string | null = null, total = items.length) {
  return {
    restarted: false,
    body: {
      status: 'ok',
      caveats: [],
      meta: { generation: 'g1' },
      data: {
        manifestVersion: 'requirements-v2+beauty2+variant-relationships@1',
        definitionCount: 154,
        slotTotal: 154,
        total,
        nextCursor,
        targets: [
          {
            target: { id: 'p01:product', level: 'product', label: 'Fixture product' },
            slotCount: 154,
          },
        ],
        items,
      },
    },
  };
}

function view(locale: 'en' | 'ar' = 'en') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale={locale} messages={locale === 'ar' ? ar : en} timeZone="UTC">
        <AttributeMatrix id="p01" />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe('AttributeMatrix', () => {
  it('bounds rendering to 25 rows and treats retailer evidence as text', async () => {
    api.page.mockResolvedValue(answer(Array.from({ length: 30 }, (_, index) => slot(index + 1))));
    const { container } = view();

    await screen.findByRole('table', { name: en.product.attributes.caption });
    expect(container.querySelectorAll('tbody tr')).toHaveLength(25);
    expect(screen.getByRole('status').textContent).toContain('Showing 25 of 30');
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
    expect(container.querySelector('img[src="x"]')).toBeNull();
    expect(api.page.mock.calls[0]?.[1].query).toMatchObject({
      target: 'p01:product',
      level: 'product',
      limit: 25,
    });
  });

  it('renders every evidence state as a distinct localized badge', async () => {
    const states: State[] = [
      'observed',
      'not_published',
      'not_observed',
      'unknown',
      'conflict',
      'invalid',
      'not_applicable',
    ];
    api.page.mockResolvedValue(answer(states.map((state, index) => slot(index + 1, state))));
    const { container } = view();

    await screen.findByRole('table');
    const badges = [...container.querySelectorAll('tbody td:nth-child(4) span')].map(
      (node) => node.textContent,
    );
    expect(badges).toEqual([
      'Observed',
      'Not published',
      'Not observed',
      'Unknown',
      'Conflict',
      'Invalid',
      'Not applicable',
    ]);
  });

  it('uses Arabic copy and RTL layout without changing exact wire values', async () => {
    api.page.mockResolvedValue(answer([slot(1)]));
    const { container } = view('ar');

    await screen.findByRole('table', { name: ar.product.attributes.caption });
    expect(container.querySelector('[data-attribute-matrix]')?.getAttribute('dir')).toBe('rtl');
    expect(screen.getAllByText('مرصود')).toHaveLength(2);
    expect(attributeValueText({ kind: 'money', amount: '12.00', minor: 1200, currency: 'AED' }, 'ar')).toBe(
      'AED 12.00',
    );
  });

  it('requests the opaque next cursor and returns focus to the result status', async () => {
    api.page
      .mockResolvedValueOnce(
        answer(
          Array.from({ length: 25 }, (_, index) => slot(index + 1)),
          'c2',
          26,
        ),
      )
      .mockResolvedValueOnce(answer([slot(26)], null, 26));
    view();
    fireEvent.click(await screen.findByRole('button', { name: en.product.attributes.next }));

    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(2));
    expect(api.page.mock.calls[1]?.[1].query.cursor).toBe('c2');
    await screen.findByText('Page 2 of 2');
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('status')));
  });
});
