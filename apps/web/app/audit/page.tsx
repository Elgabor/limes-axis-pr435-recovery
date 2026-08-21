import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { AuditExplorer } from "@/components/audit-explorer";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.audit.title,
  description: strings.pages.audit.description,
};

export default function AuditPage() {
  return (
    <ConsolePage pageKey="audit">
      <AuditExplorer />
    </ConsolePage>
  );
}
