// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils"
import { TONE_BADGE, TONE_DOT, type StatusTone } from "@/lib/statusTone"

/**
 * Status dot on its own, for filter menus and dense rows where a full pill is
 * too heavy. Decorative — the adjacent label carries the meaning.
 */
export function StatusDot({ tone, className }: { tone: StatusTone; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("h-1.5 w-1.5 flex-none rounded-full", TONE_DOT[tone], className)}
    />
  )
}

/**
 * The single status pill for the app. Spread a status meta object into it:
 * `<StatusBadge {...caseStatusMeta(c.status)} />`.
 */
export function StatusBadge({
  label,
  tone,
  className,
}: {
  label: string
  tone: StatusTone
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5",
        "text-2xs font-medium",
        TONE_BADGE[tone],
        className
      )}
    >
      <StatusDot tone={tone} />
      {label}
    </span>
  )
}
