import { setRequestLocale } from 'next-intl/server';
import { Landing } from '@/components/home/landing';
import { RequireAuth } from '@/components/require-auth';

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      <Landing />
    </RequireAuth>
  );
}
