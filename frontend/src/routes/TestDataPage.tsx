// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useState } from "react"
import { useAuth } from "react-oidc-context"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  createApTestCase,
  type CreateApTestCasePayload,
  type CreateApTestCaseResult,
} from "@/services/testDataService"

function currency(n?: number | null) {
  if (n == null) return "—"
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

interface ApPreset {
  label: string
  po_amount: number
  invoice_amount: number
  payment_block: string
  skip_gr: boolean
  po_quantity: number
  invoice_quantity: number
  gr_quantity: number
}

const AP_PRESETS: ApPreset[] = [
  {
    label: "Exact 3-way match — PO + GR + Invoice agree",
    po_amount: 25000,
    invoice_amount: 25000,
    payment_block: "R",
    skip_gr: false,
    po_quantity: 10,
    invoice_quantity: 10,
    gr_quantity: 10,
  },
  {
    label: "Price variance 5% — over-invoiced",
    po_amount: 50000,
    invoice_amount: 52500,
    payment_block: "R",
    skip_gr: false,
    po_quantity: 10,
    invoice_quantity: 10,
    gr_quantity: 10,
  },
  {
    label: "Quantity variance — invoiced 12, received 10",
    po_amount: 50000,
    invoice_amount: 50000,
    payment_block: "R",
    skip_gr: false,
    po_quantity: 10,
    invoice_quantity: 12,
    gr_quantity: 10,
  },
  {
    label: "Missing goods receipt — no GR posted",
    po_amount: 40000,
    invoice_amount: 40000,
    payment_block: "R",
    skip_gr: true,
    po_quantity: 10,
    invoice_quantity: 10,
    gr_quantity: 10,
  },
  {
    label: "Under-invoiced — partial delivery",
    po_amount: 75000,
    invoice_amount: 60000,
    payment_block: "R",
    skip_gr: false,
    po_quantity: 10,
    invoice_quantity: 8,
    gr_quantity: 8,
  },
  {
    label: "Manual payment block — exact match",
    po_amount: 40000,
    invoice_amount: 40000,
    payment_block: "B",
    skip_gr: false,
    po_quantity: 5,
    invoice_quantity: 5,
    gr_quantity: 5,
  },
]

const PAYMENT_BLOCK_LABELS: Record<string, string> = {
  R: "R — Invoice Verification",
  B: "B — Manual Payment Block",
}

export default function TestDataPage() {
  const auth = useAuth()
  const token = auth.user?.id_token ?? ""

  const [apPoAmount, setApPoAmount] = useState(50000)
  const [apInvoiceAmount, setApInvoiceAmount] = useState(52500)
  const [apPaymentBlock, setApPaymentBlock] = useState("R")
  const [apScenarioName, setApScenarioName] = useState("")
  const [apSkipGr, setApSkipGr] = useState(false)
  const [apPoQuantity, setApPoQuantity] = useState(10)
  const [apInvoiceQuantity, setApInvoiceQuantity] = useState(10)
  const [apGrQuantity, setApGrQuantity] = useState(10)
  const [apCreating, setApCreating] = useState(false)
  const [apResults, setApResults] = useState<CreateApTestCaseResult[]>([])
  const [apError, setApError] = useState<string | null>(null)

  const apVariance = apInvoiceAmount - apPoAmount
  const apVariancePct = apPoAmount > 0 ? ((apVariance / apPoAmount) * 100).toFixed(1) : "0"
  const apQtyVariance = apSkipGr ? 0 : apInvoiceQuantity - apGrQuantity

  async function handleCreateAp() {
    setApCreating(true)
    setApError(null)
    try {
      const payload: CreateApTestCasePayload = {
        po_amount: apPoAmount,
        invoice_amount: apInvoiceAmount,
        payment_block: apPaymentBlock,
        scenario_name: apScenarioName || undefined,
        skip_gr: apSkipGr,
        po_quantity: apPoQuantity,
        invoice_quantity: apInvoiceQuantity,
        gr_quantity: apGrQuantity,
      }
      const result = await createApTestCase(payload, token)
      setApResults(prev => [result, ...prev])
    } catch (e) {
      setApError(e instanceof Error ? e.message : "Creation failed")
    } finally {
      setApCreating(false)
    }
  }

  function applyApPreset(preset: ApPreset) {
    setApPoAmount(preset.po_amount)
    setApInvoiceAmount(preset.invoice_amount)
    setApPaymentBlock(preset.payment_block)
    setApScenarioName(preset.label)
    setApSkipGr(preset.skip_gr)
    setApPoQuantity(preset.po_quantity)
    setApInvoiceQuantity(preset.invoice_quantity)
    setApGrQuantity(preset.gr_quantity)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-none border-b px-6 py-4">
        <h1 className="text-xl font-semibold">Test Data — AP Invoice Matching</h1>
        <p className="text-xs text-gray-500">
          Create three-way-match exception scenarios in SAP for testing the agent. Cases appear in
          the Cases dashboard after the next poller cycle (~5 min).
        </p>
      </div>

      <div className="grow flex overflow-hidden">
        <div className="w-1/2 border-r overflow-auto p-6 space-y-5">
          <div>
            <label className="text-sm font-medium text-gray-700 mb-2 block">Quick Presets</label>
            <Select onValueChange={v => applyApPreset(AP_PRESETS[parseInt(v)])}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select an AP scenario…" />
              </SelectTrigger>
              <SelectContent>
                {AP_PRESETS.map((p, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">
                PO Amount (USD)
              </label>
              <Input
                type="number"
                min={1}
                value={apPoAmount}
                onChange={e => setApPoAmount(Number(e.target.value) || 0)}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">
                Invoice Amount (USD)
              </label>
              <Input
                type="number"
                min={1}
                value={apInvoiceAmount}
                onChange={e => setApInvoiceAmount(Number(e.target.value) || 0)}
              />
            </div>
          </div>

          <div className="flex items-center gap-3 p-3 rounded-md border bg-gray-50">
            <input
              id="skip-gr"
              type="checkbox"
              checked={apSkipGr}
              onChange={e => setApSkipGr(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300"
            />
            <label htmlFor="skip-gr" className="text-sm text-gray-700">
              <span className="font-medium">Skip Goods Receipt</span>
              <span className="text-gray-500 ml-1">— creates a "missing GR" scenario</span>
            </label>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">PO Qty</label>
              <Input
                type="number"
                min={1}
                value={apPoQuantity}
                onChange={e => setApPoQuantity(Number(e.target.value) || 1)}
              />
              <p className="text-xs text-gray-400 mt-0.5">Ordered</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">GR Qty</label>
              <Input
                type="number"
                min={0}
                value={apGrQuantity}
                disabled={apSkipGr}
                onChange={e => setApGrQuantity(Number(e.target.value) || 0)}
              />
              <p className="text-xs text-gray-400 mt-0.5">{apSkipGr ? "No GR" : "Received"}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Invoice Qty</label>
              <Input
                type="number"
                min={1}
                value={apInvoiceQuantity}
                onChange={e => setApInvoiceQuantity(Number(e.target.value) || 1)}
              />
              <p className="text-xs text-gray-400 mt-0.5">Invoiced</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Payment Block</label>
              <Select value={apPaymentBlock} onValueChange={setApPaymentBlock}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(PAYMENT_BLOCK_LABELS).map(([k, v]) => (
                    <SelectItem key={k} value={k}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Scenario Name</label>
              <Input
                placeholder="Optional label"
                value={apScenarioName}
                onChange={e => setApScenarioName(e.target.value)}
              />
            </div>
          </div>

          <Card className="p-4 bg-gray-50">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-gray-700">Three-Way Match Preview:</span>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                  apVariance === 0
                    ? "bg-green-100 text-green-800"
                    : apVariance > 0
                      ? "bg-red-100 text-red-800"
                      : "bg-yellow-100 text-yellow-800"
                }`}
              >
                {apVariance === 0
                  ? "✓ Price match"
                  : apVariance > 0
                    ? `▲ Over-invoiced ${apVariancePct}%`
                    : `▼ Under-invoiced ${apVariancePct}%`}
              </span>
              {apSkipGr ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                  ⚠ Missing GR
                </span>
              ) : (
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                    apQtyVariance === 0
                      ? "bg-green-100 text-green-800"
                      : apQtyVariance > 0
                        ? "bg-red-100 text-red-800"
                        : "bg-yellow-100 text-yellow-800"
                  }`}
                >
                  {apQtyVariance === 0
                    ? "✓ Qty match"
                    : apQtyVariance > 0
                      ? `▲ Qty +${apQtyVariance}`
                      : `▼ Qty ${apQtyVariance}`}
                </span>
              )}
            </div>
            <div className="grid grid-cols-3 gap-2 text-sm text-gray-600">
              <div>PO: {currency(apPoAmount)}</div>
              <div>Invoice: {currency(apInvoiceAmount)}</div>
              <div>Variance: {currency(apVariance)}</div>
            </div>
            {!apSkipGr && (
              <div className="grid grid-cols-3 gap-2 text-sm text-gray-600 mt-1">
                <div>PO Qty: {apPoQuantity}</div>
                <div>GR Qty: {apGrQuantity}</div>
                <div>Inv Qty: {apInvoiceQuantity}</div>
              </div>
            )}
            <p className="text-xs text-gray-500 mt-2">
              {apSkipGr
                ? "Agent will detect missing GR, check delivery tracking, and escalate to warehouse/receiving per SOP."
                : "Agent will retrieve PO, compare invoice vs GR, and route for approval or rejection based on variance tolerance."}
            </p>
          </Card>

          <Button
            className="w-full"
            disabled={
              apCreating ||
              apPoAmount <= 0 ||
              apInvoiceAmount <= 0 ||
              (!apSkipGr && apGrQuantity > apPoQuantity)
            }
            onClick={handleCreateAp}
          >
            {apCreating ? "Creating in SAP…" : "Create AP Test Case in SAP"}
          </Button>
          {!apSkipGr && apGrQuantity > apPoQuantity && (
            <div className="bg-yellow-50 border-l-4 border-yellow-400 p-3">
              <p className="text-sm text-yellow-700">
                GR quantity cannot exceed PO quantity — SAP will reject the goods receipt.
              </p>
            </div>
          )}
          {apError && (
            <div className="bg-red-50 border-l-4 border-red-500 p-3">
              <p className="text-sm text-red-700">{apError}</p>
            </div>
          )}
        </div>

        <div className="w-1/2 overflow-auto p-6">
          <h2 className="text-sm font-medium text-gray-700 mb-3">
            Created This Session ({apResults.length})
          </h2>
          {apResults.length === 0 ? (
            <p className="text-gray-400 text-center mt-12">
              No AP test cases created yet. Use the form to create blocked invoices in SAP. The
              poller will pick them up as AP exceptions.
            </p>
          ) : (
            <div className="space-y-2">
              {apResults.map((r, i) => (
                <Card key={i} className="p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-sm font-medium">{r.po_number ?? "FAILED"}</span>
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                        r.variance === 0 ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                      }`}
                    >
                      Block: {r.payment_block}{" "}
                      {r.variance !== 0 && `· ${currency(r.variance)} variance`}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-gray-500">
                    <span>PO: {currency(r.po_amount)}</span>
                    <span>Invoice: {currency(r.invoice_amount)}</span>
                    <span>
                      {r.invoice_number
                        ? `Invoice #: ${r.invoice_number}`
                        : "Invoice creation failed"}
                    </span>
                    <span>Price Δ: {currency(r.variance)}</span>
                    <span>
                      {r.skip_gr
                        ? "GR: skipped (missing)"
                        : r.gr_document
                          ? `GR: ${r.gr_document}`
                          : "GR: failed"}
                    </span>
                    <span>
                      Qty: PO {r.po_quantity}
                      {!r.skip_gr && ` → GR ${r.gr_quantity}`}
                      {` → Inv ${r.invoice_quantity}`}
                      {r.qty_variance !== 0 &&
                        ` (Δ${r.qty_variance > 0 ? "+" : ""}${r.qty_variance})`}
                    </span>
                  </div>
                  {r.scenario_name && (
                    <p className="text-xs text-gray-400 mt-1 truncate">{r.scenario_name}</p>
                  )}
                  {(r.invoice_error || r.gr_error) && (
                    <p className="text-xs text-red-400 mt-1">{r.invoice_error || r.gr_error}</p>
                  )}
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
