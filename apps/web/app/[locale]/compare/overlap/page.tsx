import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { OverlapView } from '@/components/compare/overlap-view';
import { RequireAuth } from '@/components/require-auth';

export default async function OverlapPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The pair and filters live in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <OverlapView />
      </Suspense>
    </RequireAuth>
  );
}
