// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { StatusBadge, StatusDot } from "@/components/ui/status-badge"
import { TONE_BADGE, TONE_BANNER, TONE_DOT, TONE_TEXT, type StatusTone } from "@/lib/statusTone"
import { CaseStatus, STATUS_META, caseStatusMeta } from "@/types/cases"
import { TicketStatus, TICKET_STATUS_META, ticketStatusMeta } from "@/types/tickets"

afterEach(cleanup)

describe("status tone vocabulary", () => {
  it("resolves a class for every tone in every rendering", () => {
    for (const tone of Object.keys(TONE_BADGE) as StatusTone[]) {
      expect(TONE_BADGE[tone]).toBeTruthy()
      expect(TONE_BANNER[tone]).toBeTruthy()
      expect(TONE_DOT[tone]).toBeTruthy()
      expect(TONE_TEXT[tone]).toBeTruthy()
    }
  })

  it("ships a dark variant for every tone in every rendering", () => {
    // No exemptions: a weight that clears contrast on white is too dark on the
    // dark ground, dot included — a single fill for both grounds always fails one.
    for (const tone of Object.keys(TONE_BADGE) as StatusTone[]) {
      expect(TONE_BADGE[tone]).toContain("dark:")
      expect(TONE_BANNER[tone]).toContain("dark:")
      expect(TONE_TEXT[tone]).toContain("dark:")
      expect(TONE_DOT[tone]).toContain("dark:")
    }
  })

  it("maps every case and ticket status onto a known tone", () => {
    const tones = new Set(Object.keys(TONE_BADGE))
    for (const status of Object.values(CaseStatus)) {
      expect(tones.has(STATUS_META[status].tone)).toBe(true)
    }
    for (const status of Object.values(TicketStatus)) {
      expect(tones.has(TICKET_STATUS_META[status].tone)).toBe(true)
    }
  })

  it("renders the same colour for the same meaning across domains", () => {
    // A case that finished well and a ticket that was approved are both
    // "success"; the whole point of the shared vocabulary is that they cannot
    // drift apart into two different greens.
    expect(STATUS_META[CaseStatus.Complete].tone).toBe(
      TICKET_STATUS_META[TicketStatus.Approved].tone
    )
  })

  it("falls back rather than throwing on an unrecognised status", () => {
    expect(caseStatusMeta("not-a-real-status")).toEqual(STATUS_META[CaseStatus.Detected])
    expect(ticketStatusMeta("not-a-real-status")).toEqual(TICKET_STATUS_META[TicketStatus.Open])
  })
})

describe("StatusBadge", () => {
  it("renders the label with its tone classes", () => {
    render(<StatusBadge label="Manual Review" tone="danger" />)
    const badge = screen.getByText("Manual Review")
    for (const cls of TONE_BADGE.danger.split(" ")) {
      expect(badge.className).toContain(cls)
    }
  })

  it("keeps the decorative dot out of the accessibility tree", () => {
    const { container } = render(<StatusDot tone="success" />)
    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true")
  })

  it("accepts a spread status meta object", () => {
    render(<StatusBadge {...caseStatusMeta(CaseStatus.AwaitingHumanInput)} />)
    expect(screen.getByText("Awaiting Input")).toBeTruthy()
  })
})
