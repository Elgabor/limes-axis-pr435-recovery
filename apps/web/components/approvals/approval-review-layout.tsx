"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/strings";

/** One review at a time on mobile, with the same queue and detail on desktop. */
export function ApprovalReviewLayout({ queue, detail, open, approvalId, onBack }: {
  queue: ReactNode;
  detail: ReactNode;
  open: boolean;
  approvalId?: string;
  onBack: () => void;
}) {
  const queueRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const previous = useRef({ open: false, approvalId });
  const lastOpenedId = useRef(approvalId);

  useEffect(() => {
    const mobile = window.matchMedia("(max-width: 1023px)").matches;
    if (open) {
      lastOpenedId.current = approvalId;
      if (mobile && (!previous.current.open || previous.current.approvalId !== approvalId)) {
        detailRef.current?.focus({ preventScroll: true });
        detailRef.current?.scrollIntoView({ block: "start" });
      }
    } else if (previous.current.open && mobile) {
      const opener = Array.from(queueRef.current?.querySelectorAll<HTMLButtonElement>("[data-approval-id]") ?? [])
        .find((button) => button.dataset.approvalId === lastOpenedId.current);
      const target = opener ?? queueRef.current?.querySelector<HTMLElement>("[data-queue-heading]");
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "nearest" });
    }
    previous.current = { open, approvalId };
  }, [open, approvalId]);

  return (
    <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
      <div className={cn("min-w-0", open && "hidden lg:block")} ref={queueRef}>{queue}</div>
      <section
        aria-label={strings.approvals.queue.review}
        className={cn("grid min-w-0 scroll-mt-32 gap-3 outline-none lg:scroll-mt-20", !open && "hidden lg:grid")}
        ref={detailRef}
        tabIndex={-1}
      >
        <Button className="min-h-11 w-fit lg:hidden" onClick={onBack} variant="secondary">
          <ArrowLeft aria-hidden="true" size={16} />{strings.approvals.queue.back}
        </Button>
        {detail}
      </section>
    </div>
  );
}
