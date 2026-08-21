import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { PolicyRegistry } from "@/components/policy-registry";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.policies.title,
  description: strings.pages.policies.description,
};

export default function PoliciesPage() {
  return (
    <ConsolePage pageKey="policies">
      <PolicyRegistry />
    </ConsolePage>
  );
}
