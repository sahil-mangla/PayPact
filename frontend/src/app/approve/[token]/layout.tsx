import type { Metadata } from 'next';

// The token is in the URL path: keep it out of search indexes and out of Referer headers.
export const metadata: Metadata = {
  title: 'Approve a purchase: PayPact',
  robots: { index: false, follow: false },
  referrer: 'no-referrer',
};

export default function ApproveLayout({ children }: { children: React.ReactNode }) {
  return children;
}
