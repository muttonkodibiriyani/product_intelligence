import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ASSISTANT_CONNECTED } from '@/lib/assistant';
import { STARTERS } from './starters';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AssistantView } from './assistant-view';

vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: null }) }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const show = (locale: 'en' | 'ar', connected?: boolean) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NextIntlClientProvider locale={locale} messages={locale === 'en' ? en : ar}>
        <AssistantView connected={connected} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );

describe('AssistantView', () => {
  it('is not connected yet: the page never sends a question', () => {
    expect(ASSISTANT_CONNECTED).toBe(false);
  });

  it('opens with the greeting, three starters and the composer; nothing else', () => {
    show('en');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Ryzan AI Assistant');
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe(en.assistant.hello.title);
    expect(screen.getByText(en.assistant.hello.body)).toBeTruthy();
    const starters = screen.getByRole('list', { name: en.assistant.starters });
    expect(starters.querySelectorAll('li')).toHaveLength(3);
    expect(STARTERS).toHaveLength(3);
    expect(screen.getByLabelText('Your question')).toBeTruthy();
    // The old opening: a connect panel, seven sample buttons, "sample, not live" badges.
    expect(screen.queryByRole('status')).toBeNull();
    expect(document.body.textContent).not.toMatch(/Connect to enable|not live data|Sample/);
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });

  it('the off-state is one line under the input, and Send stays off', () => {
    show('en');
    const note = screen.getByText(en.assistant.composer.disabled);
    expect(note.tagName).toBe('SPAN');
    expect(screen.getByLabelText('Your question').getAttribute('aria-describedby')).toBe(note.id);
    expect(document.body.textContent?.split(en.assistant.composer.disabled)).toHaveLength(2);
    fireEvent.click(screen.getByText(en.assistant.q.unit));
    expect((screen.getByLabelText('Your question') as HTMLTextAreaElement).value).toBe(en.assistant.q.unit);
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('once connected the line goes and Send turns on with a question', () => {
    show('en', true);
    expect(screen.queryByText(en.assistant.composer.disabled)).toBeNull();
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByText(en.assistant.q.exclusive));
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('Arabic uses the approved name, the greeting and the one-line off-state', () => {
    show('ar');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('مساعد ريزان الذكي');
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe(ar.assistant.hello.title);
    expect(screen.getByRole('list', { name: ar.assistant.starters }).querySelectorAll('li')).toHaveLength(3);
    expect(screen.getByText(ar.assistant.composer.disabled)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'إرسال' }) as HTMLButtonElement).disabled).toBe(true);
    expect(ar.app.nav.assistant).toBe('مساعد ريزان');
    expect(en.app.nav.assistant).toBe('Ryzan AI');
  });
});
