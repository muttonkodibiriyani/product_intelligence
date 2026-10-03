import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CountUp } from './count-up';
import { Tip } from './tip';

afterEach(cleanup);

describe('Tip', () => {
  it('the trigger is focusable and described by the tooltip; Escape drops focus', () => {
    render(
      <Tip text="958 of 4,790 products">
        <span>20%</span>
      </Tip>,
    );
    const tip = screen.getByRole('tooltip');
    expect(tip.textContent).toBe('958 of 4,790 products');
    const trigger = screen.getByText('20%').parentElement!;
    expect(trigger.getAttribute('tabindex')).toBe('0');
    expect(trigger.getAttribute('aria-describedby')).toBe(tip.id);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);
    fireEvent.keyDown(trigger, { key: 'Escape' });
    expect(document.activeElement).not.toBe(trigger);
  });
  it('hangs from the end edge on request', () => {
    render(
      <Tip text="x" at="end">
        <span>y</span>
      </Tip>,
    );
    expect(screen.getByRole('tooltip').getAttribute('data-at')).toBe('end');
  });
});

describe('CountUp', () => {
  it('without an IntersectionObserver (or with reduced motion) the final string is there at once', () => {
    render(<CountUp to={4812} final="4,812" format={(v) => String(Math.round(v))} />);
    expect(screen.getByText('4,812')).toBeTruthy();
  });
  it('with one it reads the API string until seen, then counts up from zero and ends on that string', () => {
    let cb: IntersectionObserverCallback = () => {};
    class IO {
      constructor(c: IntersectionObserverCallback) {
        cb = c;
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal('IntersectionObserver', IO);
    let frame: FrameRequestCallback | null = null;
    vi.stubGlobal('requestAnimationFrame', (f: FrameRequestCallback) => {
      frame = f;
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
    vi.spyOn(performance, 'now').mockReturnValue(0);
    render(<CountUp to={18.4} final="18.4%" format={(v) => `${v.toFixed(1)}%`} duration={100} />);
    // Off screen it is never 0: a reader (or a screen reader) gets the figure itself.
    expect(screen.getByText('18.4%')).toBeTruthy();
    act(() => cb([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(screen.getByText('18.4%')).toBeTruthy();
    act(() => cb([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    act(() => frame!(0));
    expect(screen.getByText('0.0%')).toBeTruthy();
    act(() => frame!(50));
    const mid = Number.parseFloat(document.body.textContent!);
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(18.4);
    act(() => frame!(100));
    expect(screen.getByText('18.4%')).toBeTruthy();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
});
