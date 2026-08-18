// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * The one place state colour is decided.
 *
 * Case status and ticket status previously carried their own independent colour
 * choices — cases on `-50`/`-700` weights, tickets on `-100`/`-800` plus emoji —
 * so the same meaning rendered differently depending on which screen you were
 * looking at. Both now map onto this vocabulary instead.
 *
 * Tones are semantic, not decorative: a tone answers "what does this state mean
 * to the operator", never "what looks nice here". Two states in the same
 * category may share a tone and be told apart by their label.
 *
 * These are still raw Tailwind palette classes. That is deliberate for now —
 * centralising them here is the prerequisite for re-mapping them onto design
 * tokens later. Add colours here, never in a component.
 */
export type StatusTone =
  /** Terminal and inert — nothing is expected to happen next. */
  | "neutral"
  /** Known and queued, no work started. */
  | "info"
  /** Work under way, no human needed. */
  | "progress"
  /** Blocked on a human decision. */
  | "attention"
  /** Finished well. */
  | "success"
  /** Failed, refused, or needs escalation. */
  | "danger"

/** Pill background and text. */
export const TONE_BADGE: Record<StatusTone, string> = {
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-400/15 dark:text-slate-300",
  info: "bg-blue-50 text-blue-800 dark:bg-blue-400/15 dark:text-blue-300",
  progress: "bg-amber-50 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300",
  attention: "bg-orange-50 text-orange-700 dark:bg-orange-400/15 dark:text-orange-300",
  success: "bg-emerald-50 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300",
  danger: "bg-red-50 text-red-700 dark:bg-red-400/15 dark:text-red-300",
}

/** Full-width notice with a left accent — errors, warnings, and inline prompts. */
export const TONE_BANNER: Record<StatusTone, string> = {
  neutral: "border-slate-400 bg-slate-50 text-slate-700 dark:bg-slate-400/10 dark:text-slate-300",
  info: "border-blue-500 bg-blue-50 text-blue-800 dark:bg-blue-400/10 dark:text-blue-300",
  progress: "border-amber-500 bg-amber-50 text-amber-800 dark:bg-amber-400/10 dark:text-amber-300",
  attention:
    "border-orange-500 bg-orange-50 text-orange-800 dark:bg-orange-400/10 dark:text-orange-300",
  success:
    "border-emerald-500 bg-emerald-50 text-emerald-800 dark:bg-emerald-400/10 dark:text-emerald-300",
  danger: "border-red-500 bg-red-50 text-red-800 dark:bg-red-400/10 dark:text-red-300",
}

/**
 * Standalone text/icon colour — a lucide icon or a count with no pill around it.
 * Weights are chosen to clear contrast on both grounds, so dark variants ship here
 * too. Use this instead of a raw `text-green-600` when the colour means a state.
 */
export const TONE_TEXT: Record<StatusTone, string> = {
  // Every light weight is -600 or -700 because this renders as text, not just as
  // an icon, so it owes 4.5:1 — and no hue clears that from -500/-600 on white
  // (blue-600 measures 3.88, red-600 4.41).
  neutral: "text-slate-600 dark:text-slate-400",
  info: "text-blue-700 dark:text-blue-400",
  progress: "text-amber-700 dark:text-amber-400",
  attention: "text-orange-700 dark:text-orange-400",
  success: "text-emerald-700 dark:text-emerald-400",
  danger: "text-red-700 dark:text-red-400",
}

/**
 * Leading dot, used both inside badges and standalone in filter menus. A dot is a
 * graphical object, so it needs 3:1 against its ground — which the -400/-500
 * weights miss on white (amber-500 measures 2.15), hence a per-ground pair here
 * rather than one fill for both.
 */
export const TONE_DOT: Record<StatusTone, string> = {
  neutral: "bg-slate-500 dark:bg-slate-400",
  info: "bg-blue-600 dark:bg-blue-400",
  progress: "bg-amber-600 dark:bg-amber-400",
  attention: "bg-orange-600 dark:bg-orange-400",
  success: "bg-emerald-600 dark:bg-emerald-400",
  danger: "bg-red-600 dark:bg-red-400",
}
