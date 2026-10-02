import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Ask, AskOptions, ChatRequest } from '@/lib/assistant/client';
import type { ChatAnswer } from '@/lib/assistant/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
import { AssistantView } from './assistant-view';

vi.mock('../auth-provider', () => ({ useAuth: () => ({ api: null }) }));

beforeEach(() => vi.stubGlobal('matchMedia', () => ({ matches: true })));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const answer: ChatAnswer = {
  status: 'answered',
  answerMd: 'Median gap is **12.5%**.',
  language: 'en',
  citations: [],
  caveats: [],
  productIds: [],
  notEnoughData: [],
  toolResults: [],
  costUsd: '0.0004',
};

/** A fake callable: records requests and lets the test drive progress and the result. */
function fake() {
  const calls: { request: ChatRequest; options: AskOptions }[] = [];
  let finish: (a: ChatAnswer) => void = () => {};
  let fail: (e: unknown) => void = () => {};
  const ask: Ask = (request, options = {}) => {
    calls.push({ request, options });
    return new Promise<ChatAnswer>((resolve, reject) => {
      finish = resolve;
      fail = reject;
      options.signal?.addEventListener('abort', () =>
        reject(Object.assign(new Error(), { code: 'functions/cancelled' })),
      );
    });
  };
  return {
    calls,
    client: () => Promise.resolve(ask),
    finish: (a: ChatAnswer) => finish(a),
    fail: (e: unknown) => fail(e),
  };
}

const show = (client: () => Promise<Ask>, locale: 'en' | 'ar' = 'en') =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale={locale} messages={locale === 'en' ? en : ar}>
        <AssistantView connected client={client} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );

const ask = async (text: string) => {
  fireEvent.change(screen.getByRole('textbox'), { target: { value: text } });
  await act(
    async () => void fireEvent.click(screen.getByRole('button', { name: en.assistant.composer.send })),
  );
};

describe('assistant thread', () => {
  it('sends one question with locale and a thread id, streams chips, then shows the answer', async () => {
    const f = fake();
    show(f.client);
    await ask('  Where are the gaps?  ');
    expect(f.calls).toHaveLength(1);
    const { request } = f.calls[0]!;
    expect(request.question).toBe('Where are the gaps?');
    expect(request.locale).toBe('en');
    expect(request.threadId).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
    expect(Object.keys(request).sort()).toEqual(['locale', 'question', 'threadId']);
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
    expect(screen.queryByText(en.assistant.samples.title)).toBeNull();
    expect(
      (screen.getByRole('button', { name: en.assistant.composer.send }) as HTMLButtonElement).disabled,
    ).toBe(true);

    act(() => {
      f.calls[0]!.options.onProgress?.({ type: 'status', stage: 'thinking' });
      f.calls[0]!.options.onProgress?.({ type: 'tool', name: 'compare', status: 'ok' });
    });
    expect(screen.getByText('Reading Price comparison')).toBeTruthy();
    await act(async () => f.finish(answer));
    expect(screen.getByText(/Median gap/)).toBeTruthy();
    expect(screen.getByText('12.5%').tagName).toBe('STRONG');
  });

  it('keeps the thread id across questions', async () => {
    const f = fake();
    show(f.client);
    await ask('one');
    await act(async () => f.finish(answer));
    await ask('two');
    expect(f.calls).toHaveLength(2);
    expect(f.calls[1]!.request.threadId).toBe(f.calls[0]!.request.threadId);
  });

  it('maps callable errors to a fixed note, never the error message', async () => {
    const f = fake();
    show(f.client);
    await ask('q');
    await act(async () =>
      f.fail(Object.assign(new Error('secret detail'), { code: 'functions/permission-denied' })),
    );
    expect(screen.getByRole('alert').textContent).toBe(en.assistant.error.noAccess);
    expect(screen.queryByText(/secret detail/)).toBeNull();
  });

  it('stop cancels the call and shows no answer or error', async () => {
    const f = fake();
    show(f.client);
    await ask('q');
    await act(
      async () => void fireEvent.click(screen.getByRole('button', { name: en.assistant.composer.stop })),
    );
    expect(f.calls[0]!.options.signal?.aborted).toBe(true);
    expect(screen.getByText(en.assistant.thread.stopped)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('a client that fails to load is the generic note', async () => {
    show(() => Promise.reject(new Error('no app')));
    await ask('q');
    expect(screen.getByRole('alert').textContent).toBe(en.assistant.error.generic);
  });

  it('Arabic page sends locale ar', async () => {
    const f = fake();
    show(f.client, 'ar');
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'سؤال' } });
    await act(
      async () => void fireEvent.click(screen.getByRole('button', { name: ar.assistant.composer.send })),
    );
    expect(f.calls[0]!.request.locale).toBe('ar');
  });
});
