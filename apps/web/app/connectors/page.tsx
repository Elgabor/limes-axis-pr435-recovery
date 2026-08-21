import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { ConnectorConsole } from "@/components/connector-console";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.connectors.title,
  description: strings.pages.connectors.description,
};

export default function ConnectorsPage() {
  return (
    <ConsolePage pageKey="connectors">
      <ConnectorConsole />
    </ConsolePage>
  );
}
