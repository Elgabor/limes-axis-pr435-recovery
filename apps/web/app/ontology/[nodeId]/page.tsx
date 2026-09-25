import type { Metadata } from "next";

import { strings } from "@/lib/strings";
import { ConsolePage } from "@/components/console-page";
import { OntologyEntityDetail } from "@/components/ontology-entity-detail";

type OntologyEntityPageProps = {
  params: Promise<{
    nodeId: string;
  }>;
};

export async function generateMetadata({ params }: OntologyEntityPageProps): Promise<Metadata> {
  const { nodeId } = await params;
  return { title: `Entity ${nodeId}` };
}

export default async function OntologyEntityPage({ params }: OntologyEntityPageProps) {
  const { nodeId } = await params;

  return (
    <ConsolePage
      pageKey="ontology"
      subtitle={strings.clarity.entityPurpose}
      title="Entity detail"
    >
      <OntologyEntityDetail nodeId={nodeId} />
    </ConsolePage>
  );
}
