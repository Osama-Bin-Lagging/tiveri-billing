import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tiveri Billing | Hospital billing demo",
  description: "Synthetic small-hospital billing workflow with HIS events, claims, pharmacy and tax review.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
