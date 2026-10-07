import { setRequestLocale } from 'next-intl/server';
import { ThreeRedirect } from '@/components/insights/three-redirect';

/** The former three-shop report: Insights with all shops selected. */
export default async function ThreeRetailerPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return <ThreeRedirect />;
}
