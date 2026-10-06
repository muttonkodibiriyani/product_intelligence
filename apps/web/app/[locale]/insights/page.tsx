import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { InsightsView } from '@/components/insights/insights-view';
import { RequireAuth } from '@/components/require-auth';

export default async function InsightsPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The pair lives in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <InsightsView />
      </Suspense>
    </RequireAuth>
  );
}
