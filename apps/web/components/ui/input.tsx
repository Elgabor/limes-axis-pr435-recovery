import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * Shared control chrome for text inputs, selects and textareas: rounded token
 * surface, hairline border, Signal focus ring, red border when invalid.
 */
export const controlClassName = cn(
  "w-full min-h-9 rounded-lg border border-line bg-surface px-3 text-sm text-ink",
  "placeholder:text-muted/70 transition-colors duration-150",
  "focus:border-signal focus:outline-none focus:ring-2 focus:ring-signal/25",
  "disabled:cursor-not-allowed disabled:opacity-55",
  "aria-[invalid=true]:border-danger aria-[invalid=true]:focus:ring-danger/25",
  "dark:border-white/15 dark:bg-white/5",
);

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(controlClassName, className)} {...rest} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(controlClassName, "resize-y py-2", className)} {...rest} />;
}
