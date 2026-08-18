// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from "react"

const STORAGE_KEY = "ui.density"

export type Density = "comfortable" | "compact"

function readInitial(): Density {
  try {
    return localStorage.getItem(STORAGE_KEY) === "compact" ? "compact" : "comfortable"
  } catch {
    // Storage can throw in private-browsing modes; comfortable is the safe default.
    return "comfortable"
  }
}

/**
 * Row density for the whole app.
 *
 * The class hangs on `document.documentElement`, like `.dark`, for two reasons:
 * Radix portals render outside the app root, and `.compact` re-declares
 * Tailwind's own `--spacing` and `--text-*` scales — which only inherit. Every
 * `p-*`/`gap-*`/`h-*` utility resolves through `--spacing`, so one class
 * restyles the app without any component knowing density exists.
 */
export function useDensity() {
  const [density, setDensity] = useState<Density>(readInitial)

  useEffect(() => {
    document.documentElement.classList.toggle("compact", density === "compact")
  }, [density])

  const toggle = useCallback(() => {
    setDensity(prev => {
      const next = prev === "compact" ? "comfortable" : "compact"
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // Persisting is best-effort; never fail a render over it.
      }
      return next
    })
  }, [])

  return { density, toggle }
}
