import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Sentiment Options Lab",
  description: "Real-time sentiment-driven options paper trading dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex">
        <Sidebar />
        <main className="flex-1 ml-56 p-6 overflow-auto">{children}</main>
      </body>
    </html>
  );
}
