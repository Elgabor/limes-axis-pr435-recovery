import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { ActionRegistry } from "@/components/action-registry";
import { Disclosure } from "@/components/ui/disclosure";
import { AgentRegistry } from "@/components/agent-registry";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.agents.title,
  description: strings.pages.agents.description,
};

export default function AgentsPage() {
  return (
    <ConsolePage pageKey="agents">
      <AgentRegistry />
      <Disclosure title={strings.clarity.actionCatalog}>
        <ActionRegistry />
      </Disclosure>
    </ConsolePage>
  );
}
