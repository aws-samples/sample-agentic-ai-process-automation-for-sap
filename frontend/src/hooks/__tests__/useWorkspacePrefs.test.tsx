// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest"
import { renderHook } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import type { ReactNode } from "react"
import { useWorkspacePrefs, usePanelSizes } from "@/hooks/useWorkspacePrefs"
import { DOMAINS } from "@/types/cases"

/**
 * The focused case arrives from two untrusted-format sources: a URL someone was
 * sent, and localStorage written by an older build. Both can carry a legacy
 * `doc#item` id, and a raw read would open the detail pane on a key the case query
 * refuses (isCaseId false) — an empty pane with no explanation. These pin the
 * normalization that routes such a value instead.
 */
function wrapper(path: string) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
  )
}

describe("useWorkspacePrefs focusedKey", () => {
  beforeEach(() => localStorage.clear())

  it("passes a canonical id through unchanged", () => {
    const { result } = renderHook(() => useWorkspacePrefs(), {
      wrapper: wrapper("/?case=5100001976-2026"),
    })
    expect(result.current.focusedKey).toBe("5100001976-2026")
  })

  it("normalizes a legacy separator from the URL", () => {
    const { result } = renderHook(() => useWorkspacePrefs(), {
      wrapper: wrapper("/?case=5100001976%232026"),
    })
    expect(result.current.focusedKey).toBe("5100001976-2026")
  })

  it("normalizes a legacy value left in localStorage by an older build", () => {
    localStorage.setItem("workspace.case", "5100001976#2026")
    const { result } = renderHook(() => useWorkspacePrefs(), { wrapper: wrapper("/") })
    expect(result.current.focusedKey).toBe("5100001976-2026")
  })

  it("reports no focused case for an unusable stored value", () => {
    localStorage.setItem("workspace.case", "not a case")
    const { result } = renderHook(() => useWorkspacePrefs(), { wrapper: wrapper("/") })
    expect(result.current.focusedKey).toBeNull()
  })

  it("reports no focused case when nothing is stored", () => {
    const { result } = renderHook(() => useWorkspacePrefs(), { wrapper: wrapper("/") })
    expect(result.current.focusedKey).toBeNull()
  })
})

describe("useWorkspacePrefs domainFilter", () => {
  beforeEach(() => localStorage.clear())

  it("defaults to the deployed domain rather than to everything", () => {
    // A scope has no everything-value: with nothing stored the operator is still an
    // operator of some domain, and `"all"` would put the list back on an unscoped read.
    const { result } = renderHook(() => useWorkspacePrefs(), { wrapper: wrapper("/") })
    expect(result.current.domainFilter).toBe(DOMAINS[0])
  })
})

/**
 * The second pane used to collapse to width 0 in list mode, so builds before the shift
 * handover wrote `[1100, 0]` under the old key. That value is length 2 and would pass any
 * shape check — restoring it would render the handover at zero width beside a blank pane,
 * with nothing on screen to explain why. The key version is what retires it.
 */
describe("usePanelSizes", () => {
  beforeEach(() => localStorage.clear())

  it("ignores a v1 collapsed-pane size instead of restoring zero width", () => {
    localStorage.setItem("workspace.panelSizes", JSON.stringify([1100, 0]))
    const { result } = renderHook(() => usePanelSizes(false))
    expect(result.current.initialSizes).toEqual([380, 720])
  })

  it("gives both modes real two-pane geometry by default", () => {
    expect(renderHook(() => usePanelSizes(false)).result.current.initialSizes).toEqual([380, 720])
    expect(renderHook(() => usePanelSizes(true)).result.current.initialSizes).toEqual([380, 720])
  })

  it("restores sizes written under the current key", () => {
    localStorage.setItem("workspace.panelSizes.v2", JSON.stringify([500, 900]))
    expect(renderHook(() => usePanelSizes(false)).result.current.initialSizes).toEqual([500, 900])
    // Each mode keeps its own width; the detail key was not written.
    expect(renderHook(() => usePanelSizes(true)).result.current.initialSizes).toEqual([380, 720])
  })

  it("discards a size list from when the chat was a third pane", () => {
    localStorage.setItem("workspace.panelSizes.v2", JSON.stringify([300, 600, 400]))
    expect(renderHook(() => usePanelSizes(false)).result.current.initialSizes).toEqual([380, 720])
  })
})
