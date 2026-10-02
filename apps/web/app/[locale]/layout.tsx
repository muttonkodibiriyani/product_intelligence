import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { NextIntlClientProvider } from 'next-intl';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { ReactNode } from 'react';
import { AppHeader } from '@/components/app-header';
import { AuthProvider } from '@/components/auth-provider';
import { formats } from '@/i18n/formats';
import { dirOf, isLocale, locales } from '@/i18n/routing';
import { loadMessages } from '@/messages/load';
import '../globals.css';

export const dynamicParams = false;
export const generateStaticParams = () => locales.map((locale) => ({ locale }));

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'app' });
  return { title: t('name'), robots: { index: false, follow: false } };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: 'app' });
  const messages = await loadMessages(locale);
  return (
    <html lang={locale} dir={dirOf(locale)}>
      <body className="min-h-screen font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:bg-surface focus:p-2"
        >
          {t('skip')}
        </a>
        <NextIntlClientProvider locale={locale} messages={messages} formats={formats}>
          <AuthProvider>
            <AppHeader />
            <main id="main" className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 sm:py-8">
              {children}
            </main>
            <footer className="mx-auto max-w-screen-2xl px-4 pb-6 text-xs text-ink-2 sm:px-6">
              <Link
                href={`/${locale}/dataset/#about-data`}
                className="text-accent underline-offset-2 hover:underline focus-visible:outline-2"
              >
                {t('aboutData')}
              </Link>
            </footer>
          </AuthProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
