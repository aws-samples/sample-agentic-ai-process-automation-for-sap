// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { WorkItem, CaseStatus, AgentTrace } from "@/types/cases"
import type { Domain } from "@/types/cases"
import { getConfig } from "@/lib/config"
import { apiFetch } from "@/lib/apiFetch"

export interface CasesFilter {
  status?: CaseStatus | "all"
  domain?: Domain
}

export async function fetchCases(filter: CasesFilter, token: string): Promise<WorkItem[]> {
  const { apiUrl } = await getConfig()
  const params = new URLSearchParams()
  if (filter.status && filter.status !== "all") {
    params.set("status", filter.status)
  }
  if (filter.domain) {
    params.set("domain", filter.domain)
  }

  return apiFetch(`${apiUrl}/cases?${params}`, { token }, "Failed to fetch cases")
}

export async function fetchCase(caseId: string, token: string): Promise<WorkItem> {
  const { apiUrl } = await getConfig()
  // case_id is the table key and is URL-safe by construction, so no encoding here.
  return apiFetch(`${apiUrl}/cases/${caseId}`, { token }, "Failed to fetch case")
}

export async function enqueueCases(caseIds: string[], token: string): Promise<void> {
  const { apiUrl } = await getConfig()
  // Backend derives the acting user from the auth token, not a field in this payload.
  await Promise.all(
    caseIds.map(caseId =>
      apiFetch(
        `${apiUrl}/cases/enqueue`,
        { token, method: "POST", body: { case_id: caseId } },
        `Failed to enqueue ${caseId}`,
        res => res.text()
      )
    )
  )
}

export async function saveAgentTrace(
  caseId: string,
  trace: AgentTrace,
  token: string
): Promise<void> {
  const { apiUrl } = await getConfig()
  await apiFetch(
    `${apiUrl}/cases/${caseId}/traces`,
    { token, method: "POST", body: trace },
    "Failed to save trace"
  )
}

export async function submitCaseRating(
  caseId: string,
  rating: "positive" | "negative",
  comment: string | undefined,
  token: string
): Promise<void> {
  const { apiUrl } = await getConfig()
  await apiFetch(
    `${apiUrl}/cases/${caseId}/rating`,
    { token, method: "PUT", body: { rating, comment } },
    "Failed to submit rating"
  )
}
