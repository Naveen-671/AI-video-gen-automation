import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI Shorts & Reels Factory | Mission Control',
  description: 'Self-hosted automated vertical video pipeline with deterministic approval gates',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
