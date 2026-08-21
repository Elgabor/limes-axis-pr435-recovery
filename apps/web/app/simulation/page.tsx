import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { SimulationConsole } from "@/components/simulation-console";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.simulation.title,
  description: strings.pages.simulation.description,
};

export default function SimulationPage() {
  return (
    <ConsolePage pageKey="simulation">
      <SimulationConsole />
    </ConsolePage>
  );
}
