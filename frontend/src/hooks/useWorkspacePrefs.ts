// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef } from "react"
import { useSearchParams } from "react-router"
import { CASE_STATUSES, DOMAINS } from "@/types/cases"
import type { CaseStatus, Domain } from "@/types/cases"
import { tryNormalizeCaseId } from "@/lib/caseKey"

const LS_PREFIX = "workspace."
// v2: the second pane used to collapse to width 0 when no case was focused, so stored
// list-mode sizes are `[1100, 0]`. That is length 2 and would restore intact, rendering
// the handover at zero width beside a blank pane. Bumping the key retires those values;
// a length check cannot.
const PANEL_SIZES_KEY = "workspace.panelSizes.v2"
const PANEL_SIZES_DETAIL_KEY = "workspace.panelSizes.detail.v2"

function readPref(params: URLSearchParams, key: string): string | null {
  return params.get(key) ?? localStorage.getItem(LS_PREFIX + key)
}

/** Set or clear a single localStorage-backed pref (the URL half is synced separately by `set()`). */
function writePref(key: string, value: string | null) {
  if (value === null) localStorage.removeItem(LS_PREFIX + key)
  else localStorage.setItem(LS_PREFIX + key, value)
}

export function useWorkspacePrefs() {
  const [searchParams, setSearchParams] = useSearchParams()

  const set = useCallback(
    (updates: Record<string, string | null>) => {
      for (const [k, v] of Object.entries(updates)) writePref(k, v)
      setSearchParams(
        prev => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(updates)) {
            if (v === null || v === "") next.delete(k)
            else next.set(k, v)
          }
          return next
        },
        { replace: true }
      )
    },
    [setSearchParams]
  )

  // Normalized through the codec, not read raw. This value arrives from a URL a
  // human may have been sent, or from localStorage written by an older build, so it
  // can carry a legacy `doc#item` id. Left as-is, such a value sets focusedKey (so
  // the detail pane opens) while failing isCaseId (so the case query stays disabled)
  // — an empty pane with nothing explaining why. Normalizing routes it instead.
  const focusedKey = tryNormalizeCaseId(readPref(searchParams, "case"))
  const setFocusedKey = useCallback((key: string | null) => set({ case: key }), [set])

  const filter: CaseStatus | "all" = (() => {
    const v = readPref(searchParams, "status")
    return v && (CASE_STATUSES as string[]).includes(v) ? (v as CaseStatus) : "all"
  })()
  const setFilter = useCallback(
    (f: CaseStatus | "all") => set({ status: f === "all" ? null : f }),
    [set]
  )

  const domainFilter: Domain = (() => {
    const v = readPref(searchParams, "domain")
    return v && (DOMAINS as string[]).includes(v) ? (v as Domain) : DOMAINS[0]
  })()
  const setDomainFilter = useCallback((d: Domain) => set({ domain: d }), [set])

  return { focusedKey, setFocusedKey, filter, setFilter, domainFilter, setDomainFilter }
}

/** Panes in the workspace split: the cases list and the detail-or-handover pane. */
const PANE_COUNT = 2

export function usePanelSizes(hasDetail: boolean) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const storageKey = hasDetail ? PANEL_SIZES_DETAIL_KEY : PANEL_SIZES_KEY
  // Both modes are real two-pane splits now — with no case focused the second pane holds
  // the shift handover rather than collapsing — so they start from the same geometry.
  // The keys stay separate because an operator may want different widths for each.
  const defaultSizes: number[] = [380, 720]

  const saved = (() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (!raw) return null
      const parsed = JSON.parse(raw) as number[]
      // Length check also discards sizes written when the chat was a third pane.
      if (Array.isArray(parsed) && parsed.length === PANE_COUNT) return parsed
    } catch {
      /* ignore */
    }
    return null
  })()

  const initialSizes = saved ?? defaultSizes

  const onPanelChange = useCallback(
    (sizes: number[]) => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        localStorage.setItem(storageKey, JSON.stringify(sizes))
      }, 300)
    },
    [storageKey]
  )

  return { initialSizes, onPanelChange }
}
