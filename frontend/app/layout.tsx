import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Personal AI Assistant",
  description: "Create and publish assistants grounded in your knowledge.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
