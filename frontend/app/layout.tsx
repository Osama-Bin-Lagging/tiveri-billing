import type { Metadata } from "next";
import "./globals.css";
import "./portal.css";
import "./invoice.css";
import "./v2.css";

export const metadata: Metadata = {
  title: "Tiveri Billing | Hospital billing demo",
  description: "Synthetic Indian hospital billing workflow: reception, doctor, diagnostics, pharmacy and billing, with a live ER data map.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
