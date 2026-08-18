// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { AssistantDock } from "./AssistantDock"
import type { AgentChat } from "@/hooks/useAgentChat"
import { clearTranscript } from "@/lib/transcript"

function makeChat(): AgentChat {
  return {
    caseId: null,
    input: "",
    setInput: vi.fn(),
    isLoading: false,
    error: null,
    setError: vi.fn(),
    sessionId: "s-1",
    ready: true,
    contextCaseCount: 0,
    setContextCases: vi.fn(),
    send: vi.fn(),
    processCase: vi.fn(),
    stop: vi.fn(),
    clear: vi.fn(),
    postNotice: vi.fn(),
    submitMessageFeedback: vi.fn(),
  } as unknown as AgentChat
}

beforeEach(() => {
  clearTranscript()
})

/**
 * C.6's remaining clause was "one position for both states". The two states used to
 * carry two different controls in two different corners, so these assert the shape of
 * the fix rather than its pixels: one control, on the leading edge, in both states.
 */
describe("AssistantDock collapse control", () => {
  it("puts the only collapse control on the leading edge in both states", () => {
    for (const collapsed of [true, false]) {
      const { unmount } = render(
        <AssistantDock chat={makeChat()} collapsed={collapsed} onToggleCollapse={vi.fn()} />
      )

      // Exactly one control toggles the panel — the vertical "Assistant" label in the
      // collapsed strip is a convenience target and carries no aria-expanded, so the
      // accessibility tree has one answer to "where do I collapse this".
      const toggles = screen
        .getAllByRole("button")
        .filter(b => b.getAttribute("aria-expanded") !== null)
      expect(toggles).toHaveLength(1)

      // Pinned to the leading edge, which is what makes the position identical across
      // states: a corner button would move when the header's contents change.
      expect(toggles[0].className).toContain("absolute")
      expect(toggles[0].className).toContain("inset-y-0")
      expect(toggles[0].className).toContain("left-0")
      expect(toggles[0].getAttribute("aria-expanded")).toBe(String(!collapsed))

      unmount()
    }
  })

  it("toggles from the edge control in both states", () => {
    for (const collapsed of [true, false]) {
      const onToggleCollapse = vi.fn()
      const { unmount } = render(
        <AssistantDock
          chat={makeChat()}
          collapsed={collapsed}
          onToggleCollapse={onToggleCollapse}
        />
      )

      const label = collapsed ? "Open the assistant" : "Collapse the assistant"
      fireEvent.click(screen.getByRole("button", { name: label }))
      expect(onToggleCollapse).toHaveBeenCalledTimes(1)

      unmount()
    }
  })
})
