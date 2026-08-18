// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"
import { apiFetch } from "@/lib/apiFetch"

export interface CreateApTestCasePayload {
  po_amount: number
  invoice_amount: number
  payment_block?: string // R = invoice verification (default), B = manual block
  scenario_name?: string
  skip_gr?: boolean // true = no goods receipt (missing GR scenario)
  po_quantity?: number
  invoice_quantity?: number
  gr_quantity?: number
}

export interface CreateApTestCaseResult {
  domain: string
  scenario_name?: string
  po_number?: string
  po_amount: number
  invoice_amount: number
  invoice_number?: string | null
  invoice_error?: string
  variance: number
  payment_block: string
  skip_gr: boolean
  po_quantity: number
  invoice_quantity: number
  gr_quantity: number
  qty_variance: number
  gr_document?: string | null
  gr_error?: string
  error?: string
}

export async function createApTestCase(
  payload: CreateApTestCasePayload,
  token: string
): Promise<CreateApTestCaseResult> {
  const { demoApiUrl } = await getConfig()
  if (!demoApiUrl) throw new Error("Demo API not configured — enable demo stack and redeploy")
  return apiFetch(
    `${demoApiUrl}/demo/test-data/ap-cases`,
    { token, method: "POST", body: payload },
    "Failed to create AP test case",
    async res => (await res.json().catch(() => ({}))).error
  )
}
