import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { OntologyExplorer } from "@/components/ontology-explorer";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.ontology.title,
  description: strings.pages.ontology.description,
};

export default function OntologyPage() {
  return (
    <ConsolePage pageKey="ontology">
      <OntologyExplorer />
    </ConsolePage>
  );
}
