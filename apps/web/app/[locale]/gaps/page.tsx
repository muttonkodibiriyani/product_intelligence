import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { GapsView } from '@/components/gaps/gaps-view';
import { RequireAuth } from '@/components/require-auth';

export default async function GapsPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The filters live in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <GapsView />
      </Suspense>
    </RequireAuth>
  );
}
