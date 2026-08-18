// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

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
import { StatusBadge } from "@/components/ui/status-badge"
import { Banner, EmptyState, PageBody, PageHeader } from "@/components/ui/page-chrome"
import { TONE_TEXT, type StatusTone } from "@/lib/statusTone"
import { formatAmount } from "@/lib/domainFields"
import {
  createApTestCase,
  type CreateApTestCasePayload,
  type CreateApTestCaseResult,
} from "@/services/testDataService"

/**
 * A variance is only ever three states, and over-invoiced is the one that blocks
 * payment — so it reads as danger while under-invoiced is merely worth noticing.
 */
export function varianceMeta(
  variance: number,
  labels: { match: string; over: string; under: string }
): { label: string; tone: StatusTone } {
  if (variance === 0) return { label: labels.match, tone: "success" }
  if (variance > 0) return { label: labels.over, tone: "danger" }
  return { label: labels.under, tone: "progress" }
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
    <>
      <PageHeader
        title="Test Data — AP Invoice Matching"
        description="Create three-way-match exception scenarios in SAP for testing the agent. Cases appear in the Cases dashboard after the next poller cycle (~5 min)."
      />

      <div className="grow flex overflow-hidden">
        <PageBody className="w-1/2 border-r space-y-5">
          <div>
            <label className="text-sm font-medium text-foreground mb-2 block">Quick Presets</label>
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
              <label className="text-sm font-medium text-foreground mb-1 block">
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
              <label className="text-sm font-medium text-foreground mb-1 block">
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

          <div className="flex items-center gap-3 p-3 rounded-md border bg-muted">
            <input
              id="skip-gr"
              type="checkbox"
              checked={apSkipGr}
              onChange={e => setApSkipGr(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <label htmlFor="skip-gr" className="text-sm text-foreground">
              <span className="font-medium">Skip Goods Receipt</span>
              <span className="text-muted-foreground ml-1">— creates a "missing GR" scenario</span>
            </label>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-sm font-medium text-foreground mb-1 block">PO Qty</label>
              <Input
                type="number"
                min={1}
                value={apPoQuantity}
                onChange={e => setApPoQuantity(Number(e.target.value) || 1)}
              />
              <p className="text-xs text-muted-foreground/70 mt-0.5">Ordered</p>
            </div>
            <div>
              <label className="text-sm font-medium text-foreground mb-1 block">GR Qty</label>
              <Input
                type="number"
                min={0}
                value={apGrQuantity}
                disabled={apSkipGr}
                onChange={e => setApGrQuantity(Number(e.target.value) || 0)}
              />
              <p className="text-xs text-muted-foreground/70 mt-0.5">
                {apSkipGr ? "No GR" : "Received"}
              </p>
            </div>
            <div>
              <label className="text-sm font-medium text-foreground mb-1 block">Invoice Qty</label>
              <Input
                type="number"
                min={1}
                value={apInvoiceQuantity}
                onChange={e => setApInvoiceQuantity(Number(e.target.value) || 1)}
              />
              <p className="text-xs text-muted-foreground/70 mt-0.5">Invoiced</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-foreground mb-1 block">
                Payment Block
              </label>
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
              <label className="text-sm font-medium text-foreground mb-1 block">
                Scenario Name
              </label>
              <Input
                placeholder="Optional label"
                value={apScenarioName}
                onChange={e => setApScenarioName(e.target.value)}
              />
            </div>
          </div>

          <Card className="p-4 bg-muted">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-foreground">Three-Way Match Preview:</span>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              {/* Glyphs dropped with the shared badge: the wording already carries
                  direction, and a screen reader announces "▲" as "up-pointing triangle". */}
              <StatusBadge
                {...varianceMeta(apVariance, {
                  match: "Price match",
                  over: `Over-invoiced ${apVariancePct}%`,
                  under: `Under-invoiced ${apVariancePct}%`,
                })}
              />
              {apSkipGr ? (
                <StatusBadge label="Missing GR" tone="attention" />
              ) : (
                <StatusBadge
                  {...varianceMeta(apQtyVariance, {
                    match: "Qty match",
                    over: `Qty over by ${apQtyVariance}`,
                    under: `Qty short by ${Math.abs(apQtyVariance)}`,
                  })}
                />
              )}
            </div>
            {/* Amounts sit in a fixed grid and change as the operator types, so the
                columns are tabular — proportional digits reflow the whole row. */}
            <div className="grid grid-cols-3 gap-2 text-sm tabular-nums text-muted-foreground">
              <div>PO: {formatAmount(apPoAmount)}</div>
              <div>Invoice: {formatAmount(apInvoiceAmount)}</div>
              <div>Variance: {formatAmount(apVariance)}</div>
            </div>
            {!apSkipGr && (
              <div className="grid grid-cols-3 gap-2 text-sm tabular-nums text-muted-foreground mt-1">
                <div>PO Qty: {apPoQuantity}</div>
                <div>GR Qty: {apGrQuantity}</div>
                <div>Inv Qty: {apInvoiceQuantity}</div>
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-2">
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
            <Banner tone="progress">
              GR quantity cannot exceed PO quantity — SAP will reject the goods receipt.
            </Banner>
          )}
          {apError && <Banner tone="danger">{apError}</Banner>}
        </PageBody>

        <PageBody className="w-1/2">
          <h2 className="text-sm font-medium text-foreground mb-3">
            Created This Session ({apResults.length})
          </h2>
          {apResults.length === 0 ? (
            <EmptyState
              message="No AP test cases created yet."
              hint="Use the form to create blocked invoices in SAP. The poller picks them up as AP exceptions."
            />
          ) : (
            <div className="space-y-2">
              {apResults.map((r, i) => (
                <Card key={i} className="p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-sm font-medium">{r.po_number ?? "FAILED"}</span>
                    <StatusBadge
                      label={
                        r.variance === 0
                          ? `Block: ${r.payment_block}`
                          : `Block: ${r.payment_block} · ${formatAmount(r.variance)} variance`
                      }
                      tone={r.variance === 0 ? "success" : "danger"}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
                    <span>PO: {formatAmount(r.po_amount)}</span>
                    <span>Invoice: {formatAmount(r.invoice_amount)}</span>
                    <span>
                      {r.invoice_number
                        ? `Invoice #: ${r.invoice_number}`
                        : "Invoice creation failed"}
                    </span>
                    <span>Price Δ: {formatAmount(r.variance)}</span>
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
                    <p className="text-xs text-muted-foreground/70 mt-1 truncate">
                      {r.scenario_name}
                    </p>
                  )}
                  {(r.invoice_error || r.gr_error) && (
                    <p className={`mt-1 text-xs ${TONE_TEXT.danger}`}>
                      {r.invoice_error || r.gr_error}
                    </p>
                  )}
                </Card>
              ))}
            </div>
          )}
        </PageBody>
      </div>
    </>
  )
}
