import { setRequestLocale } from 'next-intl/server';
import { SignInForm } from '@/components/sign-in-form';

export default async function SignIn({ params }: { params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale);
  return (
    <div className="flex justify-center pt-12">
      <SignInForm />
    </div>
  );
}
