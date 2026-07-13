// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef } from "react"
import { useSearchParams } from "react-router-dom"
import { CASE_STATUSES, DOMAINS } from "@/types/cases"
import type { CaseStatus, Domain } from "@/types/cases"

const LS_PREFIX = "workspace."
const PANEL_SIZES_KEY = "workspace.panelSizes"
const PANEL_SIZES_DETAIL_KEY = "workspace.panelSizes.detail"

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

  const focusedKey = readPref(searchParams, "case")
  const setFocusedKey = useCallback((key: string | null) => set({ case: key }), [set])

  const filter: CaseStatus | "all" = (() => {
    const v = readPref(searchParams, "status")
    return v && (CASE_STATUSES as string[]).includes(v) ? (v as CaseStatus) : "all"
  })()
  const setFilter = useCallback(
    (f: CaseStatus | "all") => set({ status: f === "all" ? null : f }),
    [set]
  )

  const domainFilter: Domain | "all" = (() => {
    const v = readPref(searchParams, "domain")
    return v && (DOMAINS as string[]).includes(v) ? (v as Domain) : "all"
  })()
  const setDomainFilter = useCallback(
    (d: Domain | "all") => set({ domain: d === "all" ? null : d }),
    [set]
  )

  return { focusedKey, setFocusedKey, filter, setFilter, domainFilter, setDomainFilter }
}

export function usePanelSizes(hasDetail: boolean) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const storageKey = hasDetail ? PANEL_SIZES_DETAIL_KEY : PANEL_SIZES_KEY
  const defaultSizes: number[] = hasDetail ? [240, 500, 400] : [450, 0, 600]

  const saved = (() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (!raw) return null
      const parsed = JSON.parse(raw) as number[]
      if (Array.isArray(parsed) && parsed.length === 3) return parsed
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
