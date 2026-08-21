"use client";

import type { ReactNode } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

/*
 * InspectDrawer is where technical depth lives: raw snake_case fields, scopes,
 * hashes and payloads move here instead of appearing as primary page copy.
 */

export interface InspectDrawerProps {
  title: string;
  record: Record<string, unknown>;
  trigger?: ReactNode;
}

type FlatField = { path: string; value: string };

function formatLeaf(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Flatten nested objects/arrays into dot/index paths with printable values. */
export function flattenRecord(record: Record<string, unknown>, prefix = ""): FlatField[] {
  const fields: FlatField[] = [];
  for (const [key, value] of Object.entries(record)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(value)) {
      if (value.length === 0) {
        fields.push({ path, value: "[]" });
      } else {
        value.forEach((item, index) => {
          if (item !== null && typeof item === "object") {
            fields.push(...flattenRecord(item as Record<string, unknown>, `${path}[${index}]`));
          } else {
            fields.push({ path: `${path}[${index}]`, value: formatLeaf(item) });
          }
        });
      }
    } else if (value !== null && typeof value === "object") {
      const nested = flattenRecord(value as Record<string, unknown>, path);
      if (nested.length === 0) {
        fields.push({ path, value: "{}" });
      } else {
        fields.push(...nested);
      }
    } else {
      fields.push({ path, value: formatLeaf(value) });
    }
  }
  return fields;
}

export function InspectDrawer({ title, record, trigger }: InspectDrawerProps) {
  const fields = flattenRecord(record);

  return (
    <Sheet>
      <SheetTrigger asChild>
        {trigger ?? (
          <button
            className="inline-flex min-h-6 cursor-pointer items-center font-mono text-xs text-muted transition-colors duration-200 hover:text-signal"
            type="button"
          >
            Inspect
          </button>
        )}
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>
            Raw record fields, exactly as the API returned them.
          </SheetDescription>
        </SheetHeader>
        <Tabs defaultValue="fields">
          <TabsList>
            <TabsTrigger value="fields">Fields</TabsTrigger>
            <TabsTrigger value="raw">Raw</TabsTrigger>
          </TabsList>
          <TabsContent value="fields">
            <dl className="m-0 flex min-w-0 flex-col gap-3">
              {fields.map((field) => (
                <div key={field.path} className="flex min-w-0 flex-col gap-0.5">
                  <dt className="m-0 font-mono text-[10.5px] font-medium tracking-[0.12em] break-words text-muted">
                    {field.path}
                  </dt>
                  <dd className="m-0 min-w-0 font-mono text-xs break-words text-ink">
                    {field.value}
                  </dd>
                </div>
              ))}
              {fields.length === 0 ? (
                <p className="m-0 text-sm text-muted">This record has no fields.</p>
              ) : null}
            </dl>
          </TabsContent>
          <TabsContent value="raw">
            <pre className="m-0 overflow-x-auto rounded-xl border border-line bg-navy/4 p-3.5 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap text-ink dark:border-white/10 dark:bg-white/4">
              {JSON.stringify(record, null, 2)}
            </pre>
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}
