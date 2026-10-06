import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { RequireAuth } from '@/components/require-auth';
import { ThreeRetailerReport } from '@/components/insights/three-retailer-report';

export default async function ThreeRetailerPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      <Suspense>
        <ThreeRetailerReport />
      </Suspense>
    </RequireAuth>
  );
}
