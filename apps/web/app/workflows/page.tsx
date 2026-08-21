import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { WorkflowConsole } from "@/components/workflow-console";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.workflows.title,
  description: strings.pages.workflows.description,
};

export default function WorkflowsPage() {
  return (
    <ConsolePage pageKey="workflows">
      <WorkflowConsole />
    </ConsolePage>
  );
}
