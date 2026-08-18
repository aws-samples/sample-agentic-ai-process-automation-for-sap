// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Relative time, in the one spelling every route uses.
 *
 * Was duplicated in WorkspacePage and TicketsDashboard; the handover would have been
 * the third copy, and three copies is how "6d" and "6 days ago" end up on the same
 * screen.
 */

/**
 * Format a timestamp as elapsed time.
 *
 * @param iso - ISO date string.
 * @returns e.g. "just now", "42m ago", "6d ago" — or `""` when there is no timestamp,
 * so a caller can render nothing rather than a fabricated age.
 */
export function timeAgo(iso?: string | null): string {
  if (!iso) return ""
  const diff = Math.max(0, Date.now() - new Date(iso).getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

/**
 * The same elapsed time as a bare magnitude, for a dense right-aligned column.
 *
 * "6d" beside a label that already says "waiting" reads better than "waiting 6d ago",
 * and the column stays narrow enough not to compete with the amount.
 */
export function shortAge(iso?: string | null): string {
  if (!iso) return "—"
  const diff = Math.max(0, Date.now() - new Date(iso).getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}
