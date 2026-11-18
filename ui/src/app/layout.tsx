import type { Metadata, Viewport } from "next";
import ErrorBoundary from '@/components/ErrorBoundary';
// Self-hosted fonts (bundled into /_next/static), so the page needs no
// internet access for fonts.
import '@fontsource/inter/300.css';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/jetbrains-mono/300.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import '@fontsource/jetbrains-mono/600.css';
import '@fontsource/jetbrains-mono/700.css';
import "./globals.css";

// Horus runs as an internal Cloudera AI Workbench Application, so there is no
// public URL, SEO metadata or social cards. The UI is derived from OSIRIS
// (MIT, see LICENSE).

export const viewport: Viewport = {
  themeColor: "#D4AF37",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  colorScheme: "dark",
};

export const metadata: Metadata = {
  title: {
    default: "Horus",
    template: "%s | Horus",
  },
  description: "Horus: live and lakehouse geospatial intelligence on Cloudera.",
  robots: { index: false, follow: false },
  icons: {
    icon: [
      { url: "/favicon-32x32.png", type: "image/png", sizes: "32x32" },
      { url: "/favicon-16x16.png", type: "image/png", sizes: "16x16" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
    shortcut: "/favicon.ico",
  },
  manifest: "/site.webmanifest",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" dir="ltr">
      <body className="antialiased">
        <ErrorBoundary name="Horus Core">
          {children}
        </ErrorBoundary>
      </body>
    </html>
  );
}
