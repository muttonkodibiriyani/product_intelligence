import { useTranslations } from 'next-intl';

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

/**
 * Why a number is withheld, in the user's language. The API's reason list is closed in the types,
 * but a newer API can send a code this build has no label for: that still reads as withheld, with
 * the code as sent, isolated so it stays left-to-right inside Arabic. No code at all (empty or
 * null) reads as plain withheld. Never blank, never a key path.
 */
export function Reason({ v }: { v: string | null | undefined }) {
  const t = useTranslations('reasons');
  const ts = useTranslations('state');
  if (!v?.trim()) return <>{ts('withheld')}</>;
  if (ENUM.test(v) && t.has(v) && typeof t.raw(v) === 'string') return <>{t(v)}</>;
  return (
    <>
      {ts.rich('withheldCode', {
        code: v,
        c: (chunks) => (
          <bdi lang="en" dir="ltr">
            {chunks}
          </bdi>
        ),
      })}
    </>
  );
}
