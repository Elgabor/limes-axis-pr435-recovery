import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { DataCatalog } from "@/components/data-catalog";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.data.title,
  description: strings.pages.data.description,
};

export default function DataPage() {
  return <ConsolePage pageKey="data"><DataCatalog /></ConsolePage>;
}
