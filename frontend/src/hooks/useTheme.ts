// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from "react"

const STORAGE_KEY = "ui.theme"

/** "system" is the absence of a choice, not a third palette — it defers to the OS. */
export type ThemePref = "light" | "dark" | "system"

const PREFS: ThemePref[] = ["light", "dark", "system"]

function readInitial(): ThemePref {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw && (PREFS as string[]).includes(raw)) return raw as ThemePref
  } catch {
    // Storage throws in private-browsing modes; following the OS is the safe default.
  }
  return "system"
}

/**
 * Whether the OS asks for dark. Guarded because jsdom (and older Safari) have no
 * matchMedia, and an unguarded call here would take down every test that mounts
 * the rail rather than just this hook.
 */
function systemPrefersDark(): boolean {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false
}

function apply(pref: ThemePref, systemDark: boolean) {
  const dark = pref === "dark" || (pref === "system" && systemDark)
  document.documentElement.classList.toggle("dark", dark)
}

/**
 * The one place the `.dark` class is set.
 *
 * Applied to `documentElement` rather than a React tree wrapper because Radix
 * portals (popovers, dialogs) render outside the app root — scoping the class to a
 * provider div would leave every portal on the light palette.
 */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readInitial)
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  useEffect(() => {
    const mql = window.matchMedia?.("(prefers-color-scheme: dark)")
    if (!mql) return
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mql.addEventListener("change", onChange)
    setSystemDark(mql.matches)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  // Applied in an effect, not in the setter: "system" has to repaint when the OS
  // flips with no user action at all.
  useEffect(() => apply(pref, systemDark), [pref, systemDark])

  const choose = useCallback((next: ThemePref) => {
    setPref(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Persisting is best-effort; never fail a render over it.
    }
  }, [])

  const resolved: "light" | "dark" = pref === "system" ? (systemDark ? "dark" : "light") : pref

  return { pref, resolved, choose }
}
