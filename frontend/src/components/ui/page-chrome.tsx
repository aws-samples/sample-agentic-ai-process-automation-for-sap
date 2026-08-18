// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils"
import { TONE_BANNER, type StatusTone } from "@/lib/statusTone"
import { DOMAINS, DOMAIN_META, type Domain } from "@/types/cases"

/**
 * The chrome every dashboard route shares: header row, empty state, error banner —
 * one definition of each so pages can't drift into their own spelling of it.
 *
 * Colour still belongs to `lib/statusTone.ts` — nothing here declares a palette
 * class of its own.
 */

/**
 * Route header: title on the left, controls on the right. Sits directly inside
 * `PageFrame`, whose column keeps it fixed while the body scrolls.
 */
export function PageHeader({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string
  description?: string
  /** Filters, refresh, and the like — right-aligned. */
  actions?: React.ReactNode
  /** Rendered next to the title, for status adornments. */
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-none items-center justify-between gap-3 border-b px-6 py-2.5",
        className
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          <h1 className="truncate font-display text-xl font-semibold tracking-tight">{title}</h1>
          {children}
        </div>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-none items-center gap-3">{actions}</div>}
    </div>
  )
}

/**
 * The routed page's body: one inset and one scroll region, so a page can't
 * re-decide its own outer box. `<main>` stays unpadded — the rail and dock own the
 * outer gutters — and this owns the page inset. `p-4`, matching the instrument
 * density of the rest of the chrome. The flex sizing (`grow` for a full page,
 * `w-1/2` for a split half) is the caller's, since only the caller knows the layout.
 */
export function PageBody({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return <div className={cn("overflow-auto p-4", className)}>{children}</div>
}

/**
 * One number and its trend. `chart` takes a sparkline rather than owning one, so
 * the kit stays free of charting dependencies.
 *
 * The value is display-face and tabular: these tiles refresh on a poll, and
 * proportional digits make the number jitter sideways on every tick.
 */
export function StatMetric({
  label,
  value,
  chart,
  className,
  style,
}: {
  label: string
  /** A node, not a number — callers animate their own counters. */
  value: React.ReactNode
  chart?: React.ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div className={cn("relative overflow-hidden", className)} style={style}>
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 font-display text-3xl font-bold tabular-nums tracking-tight">{value}</p>
      {chart}
    </div>
  )
}

/**
 * Nothing-here state. `hint` carries the "and here is how you get something"
 * half, which is the part improvised copies kept dropping.
 */
export function EmptyState({
  message,
  hint,
  className,
}: {
  message: string
  hint?: string
  className?: string
}) {
  return (
    <div className={cn("px-6 py-12 text-center", className)}>
      <p className="text-sm text-muted-foreground">{message}</p>
      {hint && <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground/80">{hint}</p>}
    </div>
  )
}

/**
 * In-flight state for a whole panel. `aria-busy` plus a polite live region does
 * the announcing; the visual is a pulse rather than a spinner because the motion
 * budget reserves spin for causality.
 */
export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div
      className="flex h-64 items-center justify-center"
      role="status"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="text-sm text-muted-foreground motion-safe:animate-pulse">{label}</span>
    </div>
  )
}

/**
 * Domain scope strip, shared across routes so it can't render a different accent
 * colour per page. A scope, not a filter — there is no everything-option. `dense` is
 * the narrow-panel geometry.
 */
export function DomainTabs({
  value,
  onChange,
  dense = false,
}: {
  value: Domain
  onChange: (next: Domain) => void
  dense?: boolean
}) {
  const tabClass = (active: boolean) =>
    cn(
      "border-b-2 font-medium transition-colors motion-reduce:transition-none",
      dense ? "flex-1 px-2 py-1 text-2xs" : "px-3 py-2 text-xs",
      active
        ? "border-foreground text-foreground"
        : "border-transparent text-muted-foreground hover:text-foreground"
    )
  return (
    <div className={cn("flex flex-none border-b", dense ? "-mx-3 px-1" : "px-6")}>
      {DOMAINS.map(d => (
        <button key={d} onClick={() => onChange(d)} className={tabClass(value === d)}>
          {DOMAIN_META[d].short}
        </button>
      ))}
    </div>
  )
}

/** Domain as a compact inline tag, for dense case rows. */
export function DomainPill({ domain }: { domain: Domain | string }) {
  return (
    <span className="rounded-sm bg-muted px-1 text-muted-foreground">
      {DOMAIN_META[domain as Domain]?.short ?? domain}
    </span>
  )
}

/**
 * Inline notice with a left accent. Tone picks the colour, so an error and a
 * warning can no longer disagree about which red or amber they meant.
 */
export function Banner({
  tone,
  children,
  className,
}: {
  tone: StatusTone
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn("flex-none border-l-4 p-3 text-sm", TONE_BANNER[tone], className)}
    >
      {children}
    </div>
  )
}
