import type { Metadata } from "next";
import "./globals.css";
import "./portal.css";
import "./invoice.css";

export const metadata: Metadata = {
  title: "Tiveri Billing | Hospital billing demo",
  description: "Synthetic Indian hospital billing workflow connecting doctor, pharmacy and billing desk.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
