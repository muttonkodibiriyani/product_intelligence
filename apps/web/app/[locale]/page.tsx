import { setRequestLocale } from 'next-intl/server';
import { DatasetStatus } from '@/components/dataset-status';
import { RequireAuth } from '@/components/require-auth';

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      <DatasetStatus />
    </RequireAuth>
  );
}
