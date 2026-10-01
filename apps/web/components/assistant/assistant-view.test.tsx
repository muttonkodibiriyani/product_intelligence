import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it } from 'vitest';
import { ASSISTANT_CONNECTED, SUGGESTED } from '@/lib/assistant';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AssistantView } from './assistant-view';

afterEach(cleanup);

const show = (locale: 'en' | 'ar', connected?: boolean) =>
  render(
    <NextIntlClientProvider locale={locale} messages={locale === 'en' ? en : ar}>
      <AssistantView connected={connected} />
    </NextIntlClientProvider>,
  );

describe('AssistantView', () => {
  it('is not connected yet: the page never sends a question', () => {
    expect(ASSISTANT_CONNECTED).toBe(false);
  });

  it('shows the name, the connect state and labelled sample questions', () => {
    show('en');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Ryzan AI Assistant');
    expect(screen.getByRole('status').textContent).toContain('Connect to enable');
    expect(screen.getByText('Sample — not live data')).toBeTruthy();
    expect(screen.getAllByRole('listitem')).toHaveLength(SUGGESTED.length);
  });

  it('a suggestion fills the question, but Send stays off while not connected', () => {
    show('en');
    fireEvent.click(screen.getByText(en.assistant.q.promo));
    expect((screen.getByLabelText('Your question') as HTMLTextAreaElement).value).toBe(en.assistant.q.promo);
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(en.assistant.composer.disabled)).toBeTruthy();
  });

  it('Send turns on with a question once connected, and the connect state goes', () => {
    show('en', true);
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.click(screen.getByText(en.assistant.q.gaps));
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('Arabic uses the approved name and labels', () => {
    show('ar');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('مساعد ريزان الذكي');
    expect(screen.getByText('نموذج — ليست بيانات حية')).toBeTruthy();
    expect(ar.app.nav.assistant).toBe('مساعد ريزان');
    expect(en.app.nav.assistant).toBe('Ryzan AI');
  });
});
