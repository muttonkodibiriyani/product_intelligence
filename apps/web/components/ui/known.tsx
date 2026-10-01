import type { useTranslations } from 'next-intl';

const ENUM = /^[a-z][a-z0-9_]{0,62}$/;

/**
 * A known enum value in the user's language; one the app doesn't know yet (a value added to the
 * API later) exactly as the API sent it, never as a message key path.
 */
export function Known({ t, k, v }: { t: ReturnType<typeof useTranslations>; k?: string; v: string }) {
  const key = k ? `${k}.${v}` : v;
  // Only an enum-shaped value is looked up, so a value with dots can't walk into another key,
  // and only a single message counts: a value that names a whole group falls back as sent.
  return ENUM.test(v) && t.has(key) && typeof t.raw(key) === 'string' ? (
    <>{t(key)}</>
  ) : (
    <span lang="en" dir="ltr">
      {v}
    </span>
  );
}
