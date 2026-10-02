import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { AssistantView } from '@/components/assistant/assistant-view';
import { RequireAuth } from '@/components/require-auth';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'assistant' });
  return { title: t('pageTitle') };
}

export default async function AssistantPage({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <RequireAuth>
      <AssistantView />
    </RequireAuth>
  );
}
