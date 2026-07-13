// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useEffect, useState } from "react"
import { useAuth } from "react-oidc-context"
import { Link, useSearchParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { Ticket, TicketStatus } from "@/types/tickets"
import { TICKET_STATUS_META, TICKET_PRIORITY_META } from "@/types/tickets"
import { fetchTickets, submitTicketAction } from "@/services/ticketsService"
import { fetchCases } from "@/services/casesService"
import { DOMAINS, DOMAIN_META, type Domain } from "@/types/cases"

function StatusBadge({ status }: { status: TicketStatus }) {
  const meta = TICKET_STATUS_META[status] ?? TICKET_STATUS_META.open
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}
    >
      {meta.emoji} {meta.label}
    </span>
  )
}

function PriorityBadge({ priority }: { priority: string }) {
  const meta =
    TICKET_PRIORITY_META[priority as keyof typeof TICKET_PRIORITY_META] ??
    TICKET_PRIORITY_META.medium
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}
    >
      {meta.label}
    </span>
  )
}

function timeAgo(iso: string): string {
  const diff = Math.max(0, Date.now() - new Date(iso).getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function TicketsDashboard() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [filter, setFilter] = useState<TicketStatus | "all">("all")
  const [domainFilter, setDomainFilter] = useState<Domain | "all">("all")
  const [caseDomainMap, setCaseDomainMap] = useState<Record<string, Domain>>({})
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const auth = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const token = auth.user?.id_token ?? ""
  const caseIdFilter = searchParams.get("case_id") || ""

  // Build case_id → domain lookup from cases list
  useEffect(() => {
    if (!token) return
    fetchCases({}, token)
      .then(cases => {
        const map: Record<string, Domain> = {}
        for (const c of cases) map[`${c.document_number}#${c.item_id}`] = c.domain
        setCaseDomainMap(map)
      })
      .catch(() => {})
  }, [token])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      if (!token) throw new Error("Not authenticated")
      let data = await fetchTickets({ status: filter }, token)
      if (caseIdFilter) data = data.filter(t => t.case_id === caseIdFilter)
      if (domainFilter !== "all")
        data = data.filter(t => t.case_id && caseDomainMap[t.case_id] === domainFilter)
      setTickets(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [filter, domainFilter, token, caseIdFilter, caseDomainMap])

  const [replyText, setReplyText] = useState("")

  async function handleAction(
    ticketId: string,
    status: "approved" | "denied" | "replied",
    resolution: string,
    responseText?: string
  ) {
    setActionLoading(true)
    try {
      const { ticket: updated } = await submitTicketAction(
        ticketId,
        status,
        resolution,
        token,
        responseText
      )
      setTickets(prev => prev.map(t => (t.ticket_id === ticketId ? updated : t)))
      if (selected?.ticket_id === ticketId) setSelected(updated)
      setReplyText("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed")
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-none border-b px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Ticket Management</h1>
          <p className="text-xs text-gray-500">
            ServiceNow-style approval queue for agent escalations
          </p>
        </div>
        <div className="flex items-center gap-3">
          {caseIdFilter && (
            <Link to={`/?case=${caseIdFilter.replace("#", "-")}`}>
              <Button size="sm" variant="outline" className="gap-1.5">
                <ArrowLeft size={14} />
                Back to Case
              </Button>
            </Link>
          )}
          {caseIdFilter && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded bg-blue-50 text-blue-700 text-xs">
              Case: {caseIdFilter}
              <button
                onClick={() =>
                  setSearchParams(prev => {
                    prev.delete("case_id")
                    return prev
                  })
                }
                className="ml-1 hover:text-blue-900"
              >
                ✕
              </button>
            </span>
          )}
          <Select value={filter} onValueChange={v => setFilter(v as TicketStatus | "all")}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder="Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {(Object.keys(TICKET_STATUS_META) as TicketStatus[]).map(s => (
                <SelectItem key={s} value={s}>
                  {TICKET_STATUS_META[s].emoji} {TICKET_STATUS_META[s].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {/* Domain tabs */}
      <div className="flex-none flex border-b px-6">
        <button
          onClick={() => setDomainFilter("all")}
          className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
            domainFilter === "all"
              ? "border-blue-500 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          All
        </button>
        {DOMAINS.map(d => (
          <button
            key={d}
            onClick={() => setDomainFilter(d)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              domainFilter === d
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {DOMAIN_META[d].short}
          </button>
        ))}
      </div>

      <div className="grow flex overflow-hidden">
        {/* Ticket list */}
        <div className="w-1/2 border-r overflow-auto p-4 space-y-2">
          {error && (
            <div className="bg-red-50 border-l-4 border-red-500 p-3 mb-2">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {loading ? (
            <p className="text-gray-500 text-center mt-12">Loading tickets…</p>
          ) : tickets.length === 0 ? (
            <p className="text-gray-500 text-center mt-12">
              No tickets found. The agent will create tickets here when it escalates exceptions.
            </p>
          ) : (
            tickets.map(t => (
              <Card
                key={t.ticket_id}
                className={`p-3 cursor-pointer hover:bg-gray-50 ${selected?.ticket_id === t.ticket_id ? "ring-2 ring-blue-500" : ""}`}
                onClick={() => setSelected(t)}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-xs text-gray-500">{t.ticket_id}</span>
                  <span className="text-xs text-gray-400">{timeAgo(t.updated_at)}</span>
                </div>
                <p className="text-sm font-medium truncate">{t.title}</p>
                <div className="flex items-center gap-2 mt-1">
                  <StatusBadge status={t.status} />
                  <PriorityBadge priority={t.priority} />
                  {t.assigned_to && (
                    <span className="text-xs text-gray-500">→ {t.assigned_to}</span>
                  )}
                </div>
              </Card>
            ))
          )}
        </div>

        {/* Detail panel */}
        <div className="w-1/2 overflow-auto p-6">
          {selected ? (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold">{selected.title}</h2>
                <div className="flex items-center gap-2 mt-1">
                  <StatusBadge status={selected.status} />
                  <PriorityBadge priority={selected.priority} />
                  <span className="text-xs text-gray-500">Created by: {selected.created_by}</span>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-1">Description</h3>
                <p className="text-sm text-gray-600 whitespace-pre-wrap">
                  {selected.description || "No description"}
                </p>
              </div>

              {selected.case_id && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-1">Related Case</h3>
                  <Link to={`/?case=${selected.case_id.replace("#", "-")}`}>
                    <Button size="sm" variant="outline" className="gap-1.5">
                      <ArrowLeft size={14} />
                      {selected.case_id}
                    </Button>
                  </Link>
                </div>
              )}

              {selected.assigned_to && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700">Assigned To</h3>
                  <p className="text-sm">{selected.assigned_to}</p>
                </div>
              )}

              {selected.resolution && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700">Resolution</h3>
                  <p className="text-sm text-gray-600">{selected.resolution}</p>
                </div>
              )}

              {/* Action buttons — only for actionable statuses */}
              {(selected.status === "open" || selected.status === "assigned") && (
                <div className="pt-2 border-t space-y-3">
                  {selected.response_type === "free_text" ? (
                    <>
                      <textarea
                        className="w-full border rounded-md p-2 text-sm min-h-[80px] resize-y"
                        placeholder="Type your reply…"
                        value={replyText}
                        onChange={e => setReplyText(e.target.value)}
                      />
                      <Button
                        size="sm"
                        disabled={actionLoading || !replyText.trim()}
                        onClick={() =>
                          handleAction(
                            selected.ticket_id,
                            "replied",
                            replyText.trim(),
                            replyText.trim()
                          )
                        }
                      >
                        💬 Send Reply
                      </Button>
                    </>
                  ) : (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={actionLoading}
                        onClick={() =>
                          handleAction(selected.ticket_id, "approved", "Approved by reviewer")
                        }
                      >
                        ✅ Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={actionLoading}
                        onClick={() =>
                          handleAction(selected.ticket_id, "denied", "Denied by reviewer")
                        }
                      >
                        🔴 Deny
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {/* Retry — re-enqueue after a decision has already been submitted */}
              {(selected.status === "approved" ||
                selected.status === "denied" ||
                selected.status === "replied") &&
                selected.case_id && (
                  <div className="pt-2 border-t">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actionLoading}
                      onClick={() =>
                        handleAction(
                          selected.ticket_id,
                          selected.status as "approved" | "denied" | "replied",
                          "Retry: re-enqueued by reviewer",
                          selected.status === "replied"
                            ? [...(selected.comments ?? [])]
                                .reverse()
                                .find(c => c.author === "user")?.text
                            : undefined
                        )
                      }
                    >
                      🔄 Retry — re-send to agent
                    </Button>
                    <p className="text-xs text-gray-400 mt-1">
                      Re-enqueues the linked case with the same decision. Use if the agent errored
                      or timed out.
                    </p>
                  </div>
                )}

              {/* Comments */}
              {selected.comments && selected.comments.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Comments</h3>
                  <div className="space-y-2">
                    {selected.comments.map((c, i) => (
                      <div key={i} className="bg-gray-50 rounded p-2">
                        <div className="flex justify-between text-xs text-gray-500">
                          <span>{c.author}</span>
                          <span>{timeAgo(c.timestamp)}</span>
                        </div>
                        <p className="text-sm mt-1">{c.text}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-gray-400 text-center mt-12">Select a ticket to view details</p>
          )}
        </div>
      </div>
    </div>
  )
}
