import type { Metadata } from "next";

import { PlatformSettingsConsole } from "@/components/platform-settings-console";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.pages.settings.title,
  description: strings.pages.settings.description,
};

export default function SettingsPage() {
  return <PlatformSettingsConsole />;
}
