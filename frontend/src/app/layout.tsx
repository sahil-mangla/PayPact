import type { Metadata } from 'next';
import '../styles/globals.css';

export const metadata: Metadata = {
  title: 'PayPact — Agent Payment Integrity Layer with PayPal',
  description:
    'Deterministic authorization, canonical proposal fingerprinting, and transaction integrity evaluation for AI purchasing agents.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body id="apil-root">{children}</body>
    </html>
  );
}
