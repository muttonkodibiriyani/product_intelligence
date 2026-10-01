import { cleanup, render } from '@testing-library/react';
import { NextIntlClientProvider, useTranslations } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import ar from '@/messages/ar.json';
import { Known } from './known';

afterEach(cleanup);

function Probe({ ns, k, v }: { ns: string; k?: string; v: string }) {
  const t = useTranslations(ns);
  return <Known t={t} k={k} v={v} />;
}

const show = (ns: string, v: string, k?: string) =>
  render(
    <NextIntlClientProvider locale="ar" messages={ar} onError={() => {}}>
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
});
