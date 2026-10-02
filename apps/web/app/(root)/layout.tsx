import type { ReactNode } from 'react';
import '../globals.css';

export const metadata = { title: 'Product Intelligence', robots: { index: false, follow: false } };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <body className="font-sans">{children}</body>
    </html>
  );
}
