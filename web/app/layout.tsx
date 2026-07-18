import type { Metadata } from "next";
import "./globals.css";
import { CasesProvider } from "@/lib/data-context";
import SourceViewerDrawer from "@/components/SourceViewerDrawer";
import AppHeader from "@/components/AppHeader";

export const metadata: Metadata = {
  title: "Evidentia — Audit Console",
  description:
    "Evidentia — provenance-first audit evidence compiler. Models understand. Code verifies. Auditors decide.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col antialiased">
        <CasesProvider>
          <AppHeader />
          {children}
          <SourceViewerDrawer />
        </CasesProvider>
      </body>
    </html>
  );
}
