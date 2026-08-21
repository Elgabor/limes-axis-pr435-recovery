import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { PlatformOverview } from "@/components/platform-overview";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.overview.title,
  description: strings.pages.overview.description,
};

export default function OverviewPage() {
  return (
    <ConsolePage pageKey="overview">
      <PlatformOverview />
    </ConsolePage>
  );
}
