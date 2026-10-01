import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { LaunchesView } from '@/components/launches/launches-view';
import { RequireAuth } from '@/components/require-auth';

export default async function LaunchesPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The filters live in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <LaunchesView />
      </Suspense>
    </RequireAuth>
  );
}
