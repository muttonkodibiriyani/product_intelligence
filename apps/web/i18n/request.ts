import { getRequestConfig } from 'next-intl/server';
import { loadMessages } from '../messages/load';
import { defaultLocale, isLocale } from './routing';

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = isLocale(requested) ? requested : defaultLocale;
  return { locale, messages: await loadMessages(locale) };
});
