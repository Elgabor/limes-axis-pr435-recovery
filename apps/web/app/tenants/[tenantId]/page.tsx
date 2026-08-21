import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { TenantDetail } from "@/components/tenant-detail";

type TenantDetailPageProps = {
  params: Promise<{
    tenantId: string;
  }>;
};

export async function generateMetadata({ params }: TenantDetailPageProps): Promise<Metadata> {
  const { tenantId } = await params;
  return { title: `Tenant ${tenantId}` };
}

export default async function TenantDetailPage({ params }: TenantDetailPageProps) {
  const { tenantId } = await params;

  return (
    <ConsolePage
      pageKey="tenants"
      subtitle="Full tenant record, lifecycle timeline with actor and audit evidence, suspend/reactivate actions and per-tenant quota administration."
      title="Tenant detail"
    >
      <TenantDetail key={tenantId} tenantId={tenantId} />
    </ConsolePage>
  );
}
