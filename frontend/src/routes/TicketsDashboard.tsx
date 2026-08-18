// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import { useFreshToken } from "@/hooks/useFreshToken"
import { Link, useSearchParams } from "react-router"
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
import { TICKET_STATUS_META, ticketPriorityMeta, ticketStatusMeta } from "@/types/tickets"
import { StatusBadge, StatusDot } from "@/components/ui/status-badge"
import {
  Banner,
  DomainTabs,
  EmptyState,
  PageBody,
  PageHeader,
  PageLoader,
} from "@/components/ui/page-chrome"
import { TicketResponseControls } from "@/components/tickets/TicketResponseControls"
import { fetchTickets, submitTicketAction } from "@/services/ticketsService"
import { fetchCases } from "@/services/casesService"
import { tryFormatCaseId, tryNormalizeCaseId } from "@/lib/caseKey"
import { timeAgo } from "@/lib/timeAgo"
import type { Domain, WorkItem } from "@/types/cases"
import { DOMAINS } from "@/types/cases"

export default function TicketsDashboard() {
  const [filter, setFilter] = useState<TicketStatus | "all">("all")
  const [domainFilter, setDomainFilter] = useState<Domain>(DOMAINS[0])
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const auth = useAuth()
  const getFreshTokens = useFreshToken()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const caseIdFilter = tryNormalizeCaseId(searchParams.get("case_id")) || ""

  // Own key, not shared with WorkspacePage's cases query: that one is keyed by
  // filter/domainFilter, which persist across sessions (URL + localStorage). Its
  // domain is now always a real domain and its status is rarely "all", so a shared
  // key would silently stop being shared.
  const casesQuery = useQuery({
    queryKey: ["cases", "unfiltered"],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCases({}, idToken)
    },
    enabled: auth.isAuthenticated,
  })
  // Whole items, not just their domain: `GET /cases` returns `agent_traces`, so the
  // proposal a ticket is asking about is already here — no second fetch to render it.
  const caseById = useMemo(() => {
    const map: Record<string, WorkItem> = {}
    for (const c of casesQuery.data ?? []) {
      const id = c.case_id ?? tryFormatCaseId(c.document_number, c.item_id)
      if (id) map[id] = c
    }
    return map
  }, [casesQuery.data])

  const ticketsQuery = useQuery({
    queryKey: ["tickets", filter],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchTickets({ status: filter }, idToken)
    },
    enabled: auth.isAuthenticated,
  })

  const tickets = useMemo(() => {
    let data = ticketsQuery.data ?? []
    // Tickets stored before the canonical form still hold `doc#item`, so both sides
    // of the comparison go through the codec.
    if (caseIdFilter) {
      data = data.filter(t => tryNormalizeCaseId(t.case_id) === caseIdFilter)
    }
    // With one domain every case is already that domain, so this filter can only
    // subtract: `caseById` comes from a second query, and while that is in flight — or
    // when a ticket outlives its case — every ticket fails the lookup and the list reads
    // empty. `"all"` used to keep this branch off the default path; the domain count does
    // now.
    if (DOMAINS.length > 1) {
      data = data.filter(t => {
        const id = tryNormalizeCaseId(t.case_id)
        return id ? caseById[id]?.domain === domainFilter : false
      })
    }
    return data
  }, [ticketsQuery.data, caseIdFilter, domainFilter, caseById])

  const loading = ticketsQuery.isLoading
  const error =
    actionError ?? (ticketsQuery.error instanceof Error ? ticketsQuery.error.message : null)

  const load = () => {
    ticketsQuery.refetch()
    casesQuery.refetch()
  }

  async function handleAction(
    ticketId: string,
    status: "approved" | "denied" | "replied",
    resolution: string,
    responseText?: string
  ) {
    setActionLoading(true)
    setActionError(null)
    try {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      const { ticket: updated } = await submitTicketAction(
        ticketId,
        status,
        resolution,
        idToken,
        responseText
      )
      queryClient.setQueryData<Ticket[]>(["tickets", filter], prev =>
        prev?.map(t => (t.ticket_id === ticketId ? updated : t))
      )
      if (selected?.ticket_id === ticketId) setSelected(updated)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed")
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Ticket Management"
        description="ServiceNow-style approval queue for agent escalations"
        actions={
          <>
            {caseIdFilter && (
              <>
                <Link to={`/?case=${caseIdFilter}`}>
                  <Button size="sm" variant="outline" className="gap-1.5">
                    <ArrowLeft size={14} />
                    Back to Case
                  </Button>
                </Link>
                <span className="inline-flex items-center gap-1 rounded bg-muted px-2 py-1 text-xs">
                  Case: {caseIdFilter}
                  <button
                    onClick={() =>
                      setSearchParams(prev => {
                        prev.delete("case_id")
                        return prev
                      })
                    }
                    className="ml-1 text-muted-foreground hover:text-foreground"
                    aria-label="Clear case filter"
                  >
                    ✕
                  </button>
                </span>
              </>
            )}
            <Select value={filter} onValueChange={v => setFilter(v as TicketStatus | "all")}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Filter" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                {(Object.keys(TICKET_STATUS_META) as TicketStatus[]).map(s => (
                  <SelectItem key={s} value={s}>
                    <span className="inline-flex items-center gap-1.5">
                      <StatusDot tone={TICKET_STATUS_META[s].tone} />
                      {TICKET_STATUS_META[s].label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={load}>
              Refresh
            </Button>
          </>
        }
      />

      {DOMAINS.length > 1 && <DomainTabs value={domainFilter} onChange={setDomainFilter} />}

      <div className="grow flex overflow-hidden">
        {/* Ticket list */}
        <PageBody className="w-1/2 border-r space-y-2">
          {error && (
            <Banner tone="danger" className="mb-2">
              {error}
            </Banner>
          )}

          {loading ? (
            <PageLoader label="Loading tickets…" />
          ) : tickets.length === 0 ? (
            <EmptyState
              message="No tickets yet."
              hint="The agent opens a ticket here when it escalates an exception."
            />
          ) : (
            tickets.map(t => (
              <Card
                key={t.ticket_id}
                className={`p-3 cursor-pointer hover:bg-muted ${selected?.ticket_id === t.ticket_id ? "ring-2 ring-ring" : ""}`}
                onClick={() => setSelected(t)}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-xs text-muted-foreground">{t.ticket_id}</span>
                  <span className="text-xs text-muted-foreground/70">{timeAgo(t.updated_at)}</span>
                </div>
                <p className="text-sm font-medium truncate">{t.title}</p>
                <div className="flex items-center gap-2 mt-1">
                  <StatusBadge {...ticketStatusMeta(t.status)} />
                  <StatusBadge {...ticketPriorityMeta(t.priority)} />
                  {t.assigned_to && (
                    <span className="text-xs text-muted-foreground">→ {t.assigned_to}</span>
                  )}
                </div>
              </Card>
            ))
          )}
        </PageBody>

        {/* Detail panel */}
        <PageBody className="w-1/2">
          {selected ? (
            <div className="space-y-4">
              <div>
                <h2 className="font-display text-lg font-semibold tracking-tight">
                  {selected.title}
                </h2>
                <div className="flex items-center gap-2 mt-1">
                  <StatusBadge {...ticketStatusMeta(selected.status)} />
                  <StatusBadge {...ticketPriorityMeta(selected.priority)} />
                  <span className="text-xs text-muted-foreground">
                    Created by: {selected.created_by}
                  </span>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-foreground mb-1">Description</h3>
                <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                  {selected.description || "No description"}
                </p>
              </div>

              {selected.case_id && (
                <div>
                  <h3 className="text-sm font-medium text-foreground mb-1">Related Case</h3>
                  <Link to={`/?case=${tryNormalizeCaseId(selected.case_id) ?? ""}`}>
                    <Button size="sm" variant="outline" className="gap-1.5">
                      <ArrowLeft size={14} />
                      {selected.case_id}
                    </Button>
                  </Link>
                </div>
              )}

              {selected.assigned_to && (
                <div>
                  <h3 className="text-sm font-medium text-foreground">Assigned To</h3>
                  <p className="text-sm">{selected.assigned_to}</p>
                </div>
              )}

              {selected.resolution && (
                <div>
                  <h3 className="text-sm font-medium text-foreground">Resolution</h3>
                  <p className="text-sm text-muted-foreground">{selected.resolution}</p>
                </div>
              )}

              {(selected.status === "open" || selected.status === "assigned") && (
                <div className="pt-2 border-t">
                  <TicketResponseControls
                    ticket={selected}
                    submitting={actionLoading}
                    traces={caseById[tryNormalizeCaseId(selected.case_id) ?? ""]?.agent_traces}
                    onAction={(action, resolution, responseText) =>
                      handleAction(selected.ticket_id, action, resolution, responseText)
                    }
                  />
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
                            ? (selected.resolution ?? undefined)
                            : undefined
                        )
                      }
                    >
                      🔄 Retry — re-send to agent
                    </Button>
                    <p className="text-xs text-muted-foreground/70 mt-1">
                      Re-enqueues the linked case with the same decision. Use if the agent errored
                      or timed out.
                    </p>
                  </div>
                )}

              {/* Comments */}
              {selected.comments && selected.comments.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-foreground mb-2">Comments</h3>
                  <div className="space-y-2">
                    {selected.comments.map((c, i) => (
                      <div key={i} className="bg-muted rounded p-2">
                        <div className="flex justify-between text-xs text-muted-foreground">
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
            <EmptyState message="Select a ticket to view details" />
          )}
        </PageBody>
      </div>
    </>
  )
}
