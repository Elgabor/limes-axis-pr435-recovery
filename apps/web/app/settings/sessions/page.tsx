import type { Metadata } from "next";

import { SessionSecurityConsole } from "@/components/session-security-console";

export const metadata: Metadata = {
  title: "Sessions",
  description: "Review and revoke active console sessions for this tenant.",
};

export default function SessionsPage() {
  return <SessionSecurityConsole />;
}
