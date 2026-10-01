import type { useTranslations } from 'next-intl';

/**
 * A known enum value in the user's language; one the app doesn't know yet (a value added to the
 * API later) exactly as the API sent it, never as a message key path.
 */
export function Known({ t, k, v }: { t: ReturnType<typeof useTranslations>; k?: string; v: string }) {
  const key = k ? `${k}.${v}` : v;
  return t.has(key) ? (
    <>{t(key)}</>
  ) : (
    <span lang="en" dir="ltr">
      {v}
    </span>
  );
}
