// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  fetchTickets,
  fetchTicket,
  createTicket,
  updateTicket,
  submitTicketAction,
} from "@/services/ticketsService"

vi.mock("@/lib/config", () => ({
  getConfig: vi.fn().mockResolvedValue({
    apiUrl: "https://api.test",
    demoApiUrl: "https://demo.test",
  }),
}))

function okJson(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  })
}

function errResponse(status: number, body: unknown = {}) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("ticketsService", () => {
  it("fetchTickets omits 'all' status, includes assigned_to", async () => {
    const fetchMock = okJson([])
    vi.stubGlobal("fetch", fetchMock)
    await fetchTickets({ status: "all" as never, assigned_to: "u1" }, "tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/tickets?assigned_to=u1")
  })

  it("fetchTickets throws on non-ok", async () => {
    vi.stubGlobal("fetch", errResponse(503))
    await expect(fetchTickets({}, "tok")).rejects.toThrow(/Failed to fetch tickets: 503/)
  })

  it("createTicket POSTs body", async () => {
    const fetchMock = okJson({ id: "T1" })
    vi.stubGlobal("fetch", fetchMock)
    await createTicket({ title: "t", description: "d" }, "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/tickets")
    expect(opts.method).toBe("POST")
    expect(JSON.parse(opts.body)).toEqual({ title: "t", description: "d" })
  })

  it("updateTicket PUTs to the ticket path", async () => {
    const fetchMock = okJson({ id: "T1" })
    vi.stubGlobal("fetch", fetchMock)
    await updateTicket("T1", { status: "closed" }, "tok")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("https://api.test/tickets/T1")
    expect(opts.method).toBe("PUT")
  })

  it("submitTicketAction builds reply comment when action is replied", async () => {
    const fetchMock = okJson({ ticket: {}, enqueued: true, case_id: "c1" })
    vi.stubGlobal("fetch", fetchMock)
    await submitTicketAction("T1", "replied", "see notes", "tok", "extra")
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.comment).toBe("see notes")
    expect(body.response_text).toBe("extra")
  })

  it("submitTicketAction sends the reviewer's own words as the comment on approval", async () => {
    // The reviewer's reason reaches both the comment list and the resumed agent —
    // `resolution` is what the SQS payload carries, so a canned comment would diverge.
    const fetchMock = okJson({ ticket: {}, enqueued: false, case_id: "c1" })
    vi.stubGlobal("fetch", fetchMock)
    await submitTicketAction("T1", "approved", "Within the 5% tolerance", "tok")
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.comment).toBe("Within the 5% tolerance")
    expect(body.resolution).toBe("Within the 5% tolerance")
    expect("response_text" in body).toBe(false)
  })

  it("fetchTicket hits the ticket path", async () => {
    const fetchMock = okJson({ id: "T1" })
    vi.stubGlobal("fetch", fetchMock)
    await fetchTicket("T1", "tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/tickets/T1")
  })

  it("fetchTickets with no filter produces a trailing ? URL", async () => {
    const fetchMock = okJson([])
    vi.stubGlobal("fetch", fetchMock)
    await fetchTickets({}, "tok")
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/tickets?")
  })
})
