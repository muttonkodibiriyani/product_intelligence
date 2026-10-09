import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider, useTranslations } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { Known, Reason } from './known';

afterEach(cleanup);

function Probe({ ns, k, v }: { ns: string; k?: string; v: string }) {
  const t = useTranslations(ns);
  return <Known t={t} k={k} v={v} />;
}

const show = (ns: string, v: string, k?: string) =>
  render(
    <NextIntlClientProvider
      locale="ar"
      messages={ar}
      onError={(e) => {
        throw e;
      }}
    >
      <Probe ns={ns} k={k} v={v} />
    </NextIntlClientProvider>,
  ).container;

describe('Known', () => {
  it('translates a known value', () => {
    expect(show('home', 'partial', 'status').textContent).toBe(ar.home.status.partial);
    expect(show('reasons', 'no_match').textContent).toBe(ar.reasons.no_match);
  });

  it('renders an unknown value as sent, marked English and LTR, never the key path', () => {
    for (const c of [show('home', 'paused', 'status'), show('reasons', 'new_reason')]) {
      const span = c.querySelector('span')!;
      expect(c.textContent).not.toContain('.');
      expect(span.getAttribute('lang')).toBe('en');
      expect(span.getAttribute('dir')).toBe('ltr');
    }
    expect(show('home', 'paused', 'status').textContent).toBe('paused');
  });

  it('never looks up a value that is not enum-shaped', () => {
    // 'status' alone names a group of messages; 'status.partial' would walk into a nested key.
    for (const [v, k] of [
      ['status', undefined],
      ['status.partial', undefined],
      ['partial.x', 'status'],
      ['Partial', 'status'],
    ] as const)
      expect(show('home', v, k).textContent).toBe(v);
  });
});

const reason = (v: string | null | undefined, locale: 'en' | 'ar' = 'ar') =>
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === 'ar' ? ar : en}
      onError={(e) => {
        throw e;
      }}
    >
      <Reason v={v} />
    </NextIntlClientProvider>,
  ).container;

describe('Reason', () => {
  it('shows the label for a reason this build knows', () => {
    expect(reason('no_match').textContent).toBe(ar.reasons.no_match);
    expect(reason('no_match', 'en').textContent).toBe(en.reasons.no_match);
    expect(reason('no_match').querySelector('bdi')).toBeNull();
  });

  // future_reason is outside the API's enum for good; window_unknown is a real code that 1218b
  // labels, and flips here when it does.
  it.each(['future_reason', 'window_unknown'])(
    'says withheld, with the code as sent, for a reason this build has no label for (%s)',
    (code) => {
      expect(reason(code, 'en').textContent).toBe(`Withheld: ${code}`);
      const c = reason(code);
      expect(c.textContent).toBe(`محجوب: ${code}`);
      const bdi = c.querySelector('bdi')!;
      expect(bdi.textContent).toBe(code);
      expect(bdi.getAttribute('dir')).toBe('ltr');
      expect(bdi.getAttribute('lang')).toBe('en');
    },
  );

  it('no code at all (empty, blank or null) reads as plain withheld, never "Withheld: " and an empty code', () => {
    for (const v of ['', '  ', null, undefined]) {
      expect(reason(v, 'en').textContent).toBe('Withheld');
      const c = reason(v);
      expect(c.textContent).toBe('محجوب');
      expect(c.querySelector('bdi')).toBeNull();
    }
  });

  it('never resolves a code that is not enum-shaped as a key path', () => {
    for (const v of ['no_match.x', 'NO_MATCH', 'status'])
      expect(reason(v, 'en').textContent).toBe(`Withheld: ${v}`);
  });
});
