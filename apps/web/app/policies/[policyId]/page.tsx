import type { Metadata } from "next";

import { strings } from "@/lib/strings";
import { ConsolePage } from "@/components/console-page";
import { PolicyDetail } from "@/components/policy-detail";

type PolicyDetailPageProps = {
  params: Promise<{
    policyId: string;
  }>;
};

export async function generateMetadata({ params }: PolicyDetailPageProps): Promise<Metadata> {
  const { policyId } = await params;
  return { title: `Policy ${policyId}` };
}

export default async function PolicyDetailPage({ params }: PolicyDetailPageProps) {
  const { policyId } = await params;

  return (
    <ConsolePage
      pageKey="policies"
      subtitle={strings.clarity.policyPurpose}
      title="Policy detail"
    >
      <PolicyDetail key={policyId} policyId={policyId} />
    </ConsolePage>
  );
}
