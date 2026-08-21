"use client";

import Link from "next/link";
import { CircleHelp, ShieldCheck } from "lucide-react";

import {
  PopoverHeader,
  popoverClass,
  popoverRowClass,
  popoverRowLinkClass,
} from "@/components/topbar/panel-chrome";
import { cn } from "@/lib/cn";

export function HelpPanel({ className }: { className?: string } = {}) {
  return (
    <section className={className ?? popoverClass} aria-label="Platform help">
      <PopoverHeader label="Platform help">
        <span className="status-pill signal-ready">Docs</span>
      </PopoverHeader>
      <div className="grid gap-2">
        <Link className={cn(popoverRowClass, popoverRowLinkClass)} href="/model-routing">
          <ShieldCheck size={16} />
          <span>
            <strong>Model routing</strong>
            <small>Inspect provider boundaries and egress decisions.</small>
          </span>
        </Link>
        <a
          className={cn(popoverRowClass, popoverRowLinkClass)}
          href="https://github.com/Limes-Labs/limes-axis/blob/main/docs/architecture.md"
          rel="noreferrer"
          target="_blank"
        >
          <CircleHelp size={16} />
          <span>
            <strong>Architecture docs</strong>
            <small>Open the public platform architecture notes.</small>
          </span>
        </a>
      </div>
    </section>
  );
}
