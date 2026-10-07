import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { DashboardView } from '@/components/dashboard/dashboard-view';
import { RequireAuth } from '@/components/require-auth';

export default async function DashboardPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The chosen view lives in the URL query, which a static page only has in the browser. */}
      <Suspense>
        <DashboardView />
      </Suspense>
    </RequireAuth>
  );
}
