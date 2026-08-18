// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { QueryClient } from "@tanstack/react-query"
import { clearTranscript } from "@/lib/transcript"

/**
 * Everything the app remembers about *what* an operator was working on, dropped when
 * the session ends.
 *
 * This runs on any transition to unauthenticated, not only the sign-out button: an
 * expired session on a shared workstation leaves the same residue. oidc-client-ts
 * removes its own stored user; nothing else here is its business.
 *
 * Three stores hold case data, and all three outlive the shell's unmount:
 *   - the transcript store — SAP tool results, so PO numbers, amounts, vendors
 *   - the React Query cache — whole case records, tickets, agent traces, metrics
 *   - localStorage — the focused case id and the queue filters around it
 *
 * The first two are memory, which a successful sign-out redirect would discard anyway
 * by unloading the tab. They are cleared explicitly because that redirect is not
 * guaranteed to land: if it fails, the shell unmounts to the sign-in card while both
 * stores keep their contents for whoever signs in next.
 */
export function clearOperatorContext(queryClient: QueryClient): void {
  clearTranscript()
  queryClient.clear()
  clearWorkspaceContext()
  stripContextFromUrl()
}

/**
 * localStorage keys that survive sign-out. An allowlist rather than a list of keys to
 * delete, so a key added later is dropped by default — the safe direction for a wipe.
 * Everything here describes the window, not the work in it.
 */
const KEEP_KEYS: readonly string[] = [
  "ui.theme",
  "ui.density",
  "ui.dock.collapsed",
  "workspace.casesCollapsed",
  "workspace.panelSizes.v2",
  "workspace.panelSizes.detail.v2",
  // A persona, not a filter: an AP manager is still an AP manager next session. Under
  // a `workspace.` prefix it reads as work, but it describes the window.
  "workspace.domain",
]

/** Drop every app-owned key that is not layout. Leaves `oidc.*` to oidc-client-ts. */
function clearWorkspaceContext(): void {
  try {
    const doomed = Object.keys(localStorage).filter(
      key => (key.startsWith("workspace.") || key.startsWith("ui.")) && !KEEP_KEYS.includes(key)
    )
    for (const key of doomed) localStorage.removeItem(key)
  } catch {
    // Storage can throw in private-browsing modes. Nothing was persisted there either.
  }
}

/**
 * The focused case and the queue filters are mirrored in the query string, so the
 * address bar names the previous operator's case until something navigates. The
 * sign-out redirect normally does; this covers the case where it never lands.
 */
function stripContextFromUrl(): void {
  if (typeof window === "undefined" || !window.location.search) return
  window.history.replaceState({}, document.title, window.location.pathname)
}
