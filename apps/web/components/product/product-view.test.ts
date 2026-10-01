import { describe, expect, it } from 'vitest';
import { safeHttpUrl } from './product-view';

describe('safeHttpUrl', () => {
  it('keeps plain web links only', () => {
    expect(safeHttpUrl('https://shop.example/p/1?x=1')).toBe('https://shop.example/p/1?x=1');
    expect(safeHttpUrl('http://shop.example/')).toBe('http://shop.example/');
    for (const bad of [
      'javascript:alert(1)',
      'JAVASCRIPT:alert(1)',
      'data:text/html,x',
      '/relative',
      '',
      null,
    ])
      expect(safeHttpUrl(bad)).toBeNull();
  });
});
