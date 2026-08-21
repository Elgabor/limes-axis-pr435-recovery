import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { ApprovalInbox } from "@/components/approval-inbox";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.approvals.title,
  description: strings.pages.approvals.description,
};

export default function ApprovalsPage() {
  return (
    <ConsolePage pageKey="approvals">
      <ApprovalInbox />
    </ConsolePage>
  );
}
