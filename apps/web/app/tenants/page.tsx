import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { TenantRegistry } from "@/components/tenant-registry";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.tenants.title,
  description: strings.pages.tenants.description,
};

export default function TenantsPage() {
  return (
    <ConsolePage pageKey="tenants">
      <TenantRegistry />
    </ConsolePage>
  );
}
