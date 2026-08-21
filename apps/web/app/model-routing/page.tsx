import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { ModelRoutingConsole } from "@/components/model-routing-console";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages["model-routing"].title,
  description: strings.pages["model-routing"].description,
};

export default function ModelRoutingPage() {
  return (
    <ConsolePage pageKey="model-routing">
      <ModelRoutingConsole />
    </ConsolePage>
  );
}
