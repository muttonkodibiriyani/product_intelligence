import { setRequestLocale } from 'next-intl/server';
import { DatasetStatus } from '@/components/dataset-status';
import { RequireAuth } from '@/components/require-auth';

/** The dataset on its own page: what is collected, each shop's status, and "About the data". */
export default async function DatasetPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      <div id="dataset" className="panel px-5 py-4">
        <DatasetStatus />
      </div>
    </RequireAuth>
  );
}
