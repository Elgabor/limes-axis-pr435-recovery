import {
  platformStatusClass,
  platformStatusLabel,
  type PlatformStatus,
} from "@/lib/platform-overview";

/** Pill for the API's ready / watch / action_required platform statuses. */
export function PlatformStatusPill({ status }: { status: PlatformStatus }) {
  return (
    <span className={`status-pill ${platformStatusClass(status)}`}>
      {platformStatusLabel(status)}
    </span>
  );
}
