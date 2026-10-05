import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Manrope } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// What the three minds are actually read in. Geist runs the chrome; the
// messages get their own face so a line of speech never looks like a label.
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Other Minds",
  description:
    "AI agents with distinct philosophical stances discuss your question.",
};

/**
 * Mobile browser chrome. Without `themeColor` the address bar stays the OS
 * default — a bright bar sitting directly above a near-black room, which is
 * the first thing you see on a phone. `--bg` is not readable from here, so the
 * literal is the one place it is repeated; it is checked by a test.
 *
 * Deliberately NOT setting maximumScale/userScalable: Next already emits
 * `width=device-width, initial-scale=1`, and locking scale would take
 * pinch-zoom away from anyone who needs it. The iOS focus-zoom problem is
 * fixed where it belongs, with a 16px input (see globals.css).
 */
export const viewport: Viewport = {
  themeColor: "#0a0a10",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${manrope.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
