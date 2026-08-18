// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from "react"

/**
 * Collapse state for a panel that persists the choice across reloads — the side
 * rail, the assistant dock, the workspace's cases list.
 *
 * @param storageKey - localStorage key; distinct per panel, or they would toggle as one.
 * @param shortcut - single letter, combined with Cmd/Ctrl. Omit for a panel that only
 * collapses by click or drag.
 */
export function usePanelCollapsed(storageKey: string, shortcut?: string) {
  const [collapsed, setCollapsedState] = useState(() => {
    try {
      return localStorage.getItem(storageKey) === "1"
    } catch {
      // Storage can throw in private-browsing modes; an open panel is a safe default.
      return false
    }
  })

  const setCollapsed = useCallback(
    (next: boolean) => {
      try {
        localStorage.setItem(storageKey, next ? "1" : "0")
      } catch {
        // Persisting is best-effort; never fail a render over it.
      }
      setCollapsedState(next)
    },
    [storageKey]
  )

  const toggle = useCallback(() => setCollapsed(!collapsed), [setCollapsed, collapsed])

  useEffect(() => {
    if (!shortcut) return
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === shortcut) {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [toggle, shortcut])

  return { collapsed, setCollapsed, toggle }
}
