import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { ActionRegistry } from "@/components/action-registry";
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
      <ActionRegistry />
    </ConsolePage>
  );
}
