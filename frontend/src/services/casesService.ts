// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { WorkItem, CaseStatus, AgentTrace } from "@/types/cases"
import type { Domain } from "@/types/cases"
import { getConfig } from "@/lib/config"

export interface CasesFilter {
  status?: CaseStatus | "all"
  domain?: Domain | "all"
}

export async function fetchCases(filter: CasesFilter, token: string): Promise<WorkItem[]> {
  const { apiUrl } = await getConfig()
  const params = new URLSearchParams()
  if (filter.status && filter.status !== "all") {
    params.set("status", filter.status)
  }
  if (filter.domain && filter.domain !== "all") {
    params.set("domain", filter.domain)
  }

  const res = await fetch(`${apiUrl}/cases?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  })

  if (!res.ok) throw new Error(`Failed to fetch cases: ${res.status}`)
  return res.json()
}

export async function fetchCase(
  documentNumber: string,
  itemId: string,
  token: string
): Promise<WorkItem> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/cases/${documentNumber}/${itemId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })

  if (!res.ok) throw new Error(`Failed to fetch case: ${res.status}`)
  return res.json()
}

export async function enqueueCases(caseIds: string[], token: string): Promise<void> {
  const { apiUrl } = await getConfig()
  // Backend derives the acting user from the auth token, not a field in this payload.
  await Promise.all(
    caseIds.map(async caseId => {
      const res = await fetch(`${apiUrl}/cases/enqueue`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId }),
      })
      if (!res.ok) {
        const detail = await res.text().catch(() => "")
        throw new Error(detail || `Failed to enqueue ${caseId}: ${res.status}`)
      }
    })
  )
}

export async function saveAgentTrace(
  documentNumber: string,
  itemId: string,
  trace: AgentTrace,
  token: string
): Promise<void> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/cases/${documentNumber}/${itemId}/traces`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(trace),
  })

  if (!res.ok) throw new Error(`Failed to save trace: ${res.status}`)
}

export async function submitCaseRating(
  documentNumber: string,
  itemId: string,
  rating: "positive" | "negative",
  comment: string | undefined,
  token: string
): Promise<void> {
  const { apiUrl } = await getConfig()
  const res = await fetch(`${apiUrl}/cases/${documentNumber}/${itemId}/rating`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ rating, comment }),
  })
  if (!res.ok) throw new Error(`Failed to submit rating: ${res.status}`)
}
