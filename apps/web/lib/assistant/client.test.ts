import { describe, expect, it } from 'vitest';
import { chatErrorKey, isChatAnswer, isProgress } from './client';

describe('callable client guards', () => {
  it('accepts only known progress events', () => {
    expect(isProgress({ type: 'status', stage: 'thinking' })).toBe(true);
    expect(isProgress({ type: 'tool', name: 'compare', status: 'ok' })).toBe(true);
    expect(isProgress({ type: 'status', stage: 'typing' })).toBe(false);
    expect(isProgress({ type: 'text', delta: 'Median…' })).toBe(false);
    expect(isProgress(null)).toBe(false);
  });

  it('refuses a response that is not the answer contract', () => {
    const ok = {
      status: 'answered',
      answerMd: 'x',
      citations: [],
      caveats: [],
      productIds: [],
      notEnoughData: [],
      toolResults: [],
    };
    expect(isChatAnswer(ok)).toBe(true);
    expect(isChatAnswer({ ...ok, status: 'draft' })).toBe(false);
    expect(isChatAnswer({ ...ok, citations: undefined })).toBe(false);
    expect(isChatAnswer('answer')).toBe(false);
  });

  it('maps callable error codes', () => {
    expect(chatErrorKey({ code: 'functions/unauthenticated' })).toBe('signedOut');
    expect(chatErrorKey({ code: 'functions/permission-denied' })).toBe('noAccess');
    expect(chatErrorKey({ code: 'functions/deadline-exceeded' })).toBe('timeout');
    expect(chatErrorKey({ code: 'functions/unavailable' })).toBe('network');
    expect(chatErrorKey({ code: 'functions/internal' })).toBe('generic');
    expect(chatErrorKey(new Error('x'))).toBe('generic');
  });
});
