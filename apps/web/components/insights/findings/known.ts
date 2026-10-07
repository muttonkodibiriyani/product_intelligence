import type { useTranslations } from 'next-intl';

const ENUM = /^[a-z][a-z0-9_]{0,62}$/;

/**
 * An enum value or code through the messages when known (`group.value`), else exactly as the API
 * sent it: only an enum-shaped value is looked up, and only a single message counts (as `Known`).
 */
export function known(t: ReturnType<typeof useTranslations>, group: string, v: string): string {
  const key = group ? `${group}.${v}` : v;
  return ENUM.test(v) && t.has(key) && typeof t.raw(key) === 'string' ? t(key) : v;
}
