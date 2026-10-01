import { setRequestLocale } from 'next-intl/server';
import { Suspense } from 'react';
import { Explorer } from '@/components/explore/explorer';
import { RequireAuth } from '@/components/require-auth';

export default async function ExplorePage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      {/* The explorer reads its state from the URL query, which a static page only has in the browser. */}
      <Suspense>
        <Explorer />
      </Suspense>
    </RequireAuth>
  );
}
