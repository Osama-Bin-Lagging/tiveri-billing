import type { Metadata } from "next";
import "./globals.css";
import "./portal.css";

export const metadata: Metadata = {
  title: "Tiveri Billing | Hospital billing demo",
  description: "Synthetic hospital billing workflow with clinical, coding, pharmacy and finance roles.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
