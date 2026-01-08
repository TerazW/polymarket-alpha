import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Belief Reaction System",
  description: "Real-time market belief monitoring for Polymarket",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
