// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react"
import {
  AlertTriangle,
  Bell,
  Bot,
  Calculator,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Database,
  FileText,
  PenLine,
  Timer,
  Unplug,
  User,
  Webhook,
  XCircle,
} from "lucide-react"
import {
  AuthzMode,
  AuthzOutcome,
  EvidenceKind,
  TraceSegmentType,
  Trigger,
  WriteOp,
} from "@/types/cases"
import type { AgentTrace, EvidenceAuthz, EvidenceField, TraceSegment } from "@/types/cases"
import { rowHeadline, segmentStatus, segmentsOf, splitProse } from "@/lib/caseTimeline"
import { appliedRows, baselineFor, functionImportCard, proposedRows } from "@/lib/writeDiff"
import { TONE_BADGE, TONE_TEXT } from "@/lib/statusTone"
import { EmptyState } from "@/components/ui/page-chrome"
import { MarkdownRenderer } from "@/components/chat/MarkdownRenderer"
import { ToolCallDisplay } from "@/components/chat/ToolCallDisplay"
import { WriteDiff } from "@/components/case/WriteDiff"
import { cn } from "@/lib/utils"

/**
 * A processed case renders as its decision chain, not as a conversation.
 *
 * The run that produced the case's current state is never behind a click; earlier
 * runs collapse beneath it, because re-processing a case is an event a controller
 * needs to see as distinct. Rows are driven by `evidence.kind`, so nothing here
 * pattern-matches a tool name.
 */

// Trigger is categorical, not state — a poller is not "info" and a webhook is not
// "success" — so these keep distinct hues rather than mapping onto the tone set.
const TRIGGER_STYLE: Record<string, { icon: typeof Bot; color: string; label: string }> = {
  [Trigger.Manual]: {
    icon: User,
    color: "bg-blue-100 text-blue-800 dark:bg-blue-400/15 dark:text-blue-300",
    label: "Manual",
  },
  [Trigger.Poller]: {
    icon: Timer,
    color: "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300",
    label: "Poller",
  },
  [Trigger.Batch]: {
    icon: Timer,
    color: "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300",
    label: "Batch",
  },
  [Trigger.TicketAction]: {
    icon: User,
    color: "bg-blue-100 text-blue-800 dark:bg-blue-400/15 dark:text-blue-300",
    label: "Ticket",
  },
  [Trigger.WebhookSes]: {
    icon: Webhook,
    color: "bg-purple-100 text-purple-800 dark:bg-purple-400/15 dark:text-purple-300",
    label: "Email",
  },
  [Trigger.WebhookJira]: {
    icon: Webhook,
    color: "bg-purple-100 text-purple-800 dark:bg-purple-400/15 dark:text-purple-300",
    label: "Jira",
  },
  [Trigger.WebhookServicenow]: {
    icon: Webhook,
    color: "bg-purple-100 text-purple-800 dark:bg-purple-400/15 dark:text-purple-300",
    label: "ServiceNow",
  },
}

// Outcome is state, so colour comes from the tone vocabulary.
const OUTCOME_STYLE: Record<string, { icon: typeof CheckCircle2; color: string; label: string }> = {
  complete: { icon: CheckCircle2, color: TONE_TEXT.success, label: "Completed" },
  stopped: { icon: AlertTriangle, color: TONE_TEXT.progress, label: "Stopped early" },
  cancelled: { icon: AlertTriangle, color: TONE_TEXT.progress, label: "Stopped early" },
  error: { icon: XCircle, color: TONE_TEXT.danger, label: "Error" },
  disconnected: { icon: Unplug, color: "text-muted-foreground", label: "Disconnected" },
}

const KIND_ICON: Record<string, typeof Database> = {
  [EvidenceKind.SapRead]: Database,
  [EvidenceKind.SapWrite]: PenLine,
  [EvidenceKind.SopLookup]: FileText,
  [EvidenceKind.CaseUpdate]: Check,
  [EvidenceKind.Notification]: Bell,
  [EvidenceKind.Computation]: Calculator,
}

/** Relative date label for grouping prior runs. */
function dateLabel(ts: string): string {
  const d = new Date(ts)
  const diff = Math.floor((Date.now() - d.getTime()) / 86_400_000)
  if (diff === 0) return "Today"
  if (diff === 1) return "Yesterday"
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function timeLabel(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

function TriggerBadge({ trigger }: { trigger?: string }) {
  const style = TRIGGER_STYLE[trigger ?? ""] ?? {
    icon: Bot,
    color: "bg-muted text-foreground",
    label: "Agent",
  }
  const Icon = style.icon
  return (
    <span
      className={cn(
        "inline-flex flex-none items-center gap-1 rounded-sm px-1.5 py-0.5 text-3xs font-medium",
        style.color
      )}
    >
      <Icon size={10} />
      {style.label}
    </span>
  )
}

function OutcomeBadge({ outcome }: { outcome?: string }) {
  const style = OUTCOME_STYLE[outcome ?? ""]
  if (!style) return null
  const Icon = style.icon
  return (
    <span
      className={cn("inline-flex flex-none items-center gap-0.5 text-3xs font-medium", style.color)}
    >
      <Icon size={10} />
      {style.label}
    </span>
  )
}

/** All text content of a run, for clipboard copy. */
function traceText(trace: AgentTrace): string {
  return segmentsOf(trace)
    .filter(s => s?.type === TraceSegmentType.Text && s.content)
    .map(s => s.content!)
    .join("\n\n")
}

function CopyButton({ trace }: { trace: AgentTrace }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      aria-label="Copy this run's text"
      title="Copy this run's text"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(traceText(trace))
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        } catch {
          /* clipboard unavailable — nothing to report, the text is on screen */
        }
      }}
      className="flex-none rounded-md p-1 text-muted-foreground transition-colors motion-reduce:transition-none hover:bg-accent hover:text-foreground"
    >
      {copied ? <Check size={12} className={TONE_TEXT.success} /> : <Copy size={12} />}
    </button>
  )
}

/**
 * Whether the write was authorized or merely logged. Writes only: a chip on every
 * read is noise that trains an operator to stop reading it, and it is the write that
 * Cedar is there to gate. Reads carry `authz` in the expanded detail.
 *
 * The decision leads, because "was this allowed" is the question — mode only
 * qualifies how much the answer was worth. A rejected write under LOG_ONLY still
 * reached SAP, so that pairing is the one an operator most needs to see, and it
 * takes `danger` rather than the mode's neutral.
 */
function AuthzChip({ authz }: { authz?: EvidenceAuthz }) {
  // A write that never traversed policy evaluation is not "logged only" — it was
  // not evaluated at all. That is the OBO topology, and saying so is the point.
  if (!authz) return null
  if (!authz.via_gateway) {
    return (
      <span
        className={cn(
          "inline-flex flex-none items-center rounded-full px-1.5 py-0.5 text-3xs font-medium",
          TONE_BADGE.attention
        )}
        title="This write bypassed our Gateway, so Cedar never evaluated it"
      >
        Cedar: not evaluated
      </span>
    )
  }

  const enforced = authz.mode === AuthzMode.Enforce
  const modeNote = enforced
    ? "a denial would have blocked it"
    : "log-only mode — a denial would not have blocked it"
  const rejected = authz.outcome === AuthzOutcome.Rejected
  const permitted = authz.outcome === AuthzOutcome.Permitted

  return (
    <span
      className={cn(
        "inline-flex flex-none items-center rounded-full px-1.5 py-0.5 text-3xs font-medium",
        // Absent outcome is not a denial: the call failed for some other reason and
        // the row's own error state already reports that.
        rejected
          ? TONE_BADGE.danger
          : permitted && enforced
            ? TONE_BADGE.success
            : TONE_BADGE.neutral
      )}
      title={
        rejected
          ? `Cedar rejected this write — ${modeNote}`
          : permitted
            ? `Cedar permitted this write — ${modeNote}`
            : `Cedar evaluated this write in ${enforced ? "enforce" : "log-only"} mode; the call failed for a non-authorization reason, so no decision was recorded`
      }
    >
      {rejected ? "Cedar: rejected" : permitted ? "Cedar: permitted" : "Cedar: no decision"}
      {!enforced && (rejected || permitted) && " (log only)"}
    </span>
  )
}

function FieldList({ fields }: { fields: EvidenceField[] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-2xs">
      {fields.map((f, i) => (
        // Names are not unique: `_scalar_fields` appends its own `result` field, so a
        // tool whose args already carry one produces two rows named `result`.
        <div key={`${f.name}-${i}`} className="contents">
          <dt className="text-muted-foreground">{f.name}</dt>
          {/* Mono because an operator compares this against another screen. */}
          <dd className="font-mono break-all text-foreground">{f.value || "—"}</dd>
        </div>
      ))}
    </dl>
  )
}

/** `steps` is the whole run, because a write's before values come from an earlier read. */
function EvidenceRow({ segment, steps }: { segment: TraceSegment; steps: TraceSegment[] }) {
  const [open, setOpen] = useState(false)
  const evidence = segment.evidence!
  const failed = segmentStatus(segment) === "error"
  const Icon = KIND_ICON[evidence.kind] ?? Bot
  const isWrite = evidence.kind === EvidenceKind.SapWrite
  const proposal = evidence.proposed_write
  // Both arrive as JSON from DynamoDB and `Evidence`'s index signature admits any
  // shape, so a stored scalar would throw in `.map` and blank the route.
  const clauses = Array.isArray(evidence.clauses_retrieved) ? evidence.clauses_retrieved : []
  const fields = Array.isArray(evidence.fields) ? evidence.fields : []
  const hasDetail =
    fields.length > 0 ||
    clauses.length > 0 ||
    Boolean(evidence.source) ||
    Boolean(evidence.at) ||
    Boolean(proposal) ||
    (!isWrite && Boolean(evidence.authz))

  return (
    <li className="rounded-md border">
      <button
        type="button"
        // A row with nothing behind it is still a button — it carries the headline and
        // has to stay reachable — but it must not claim a disclosure it cannot open.
        aria-expanded={hasDetail ? open : undefined}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs transition-colors motion-reduce:transition-none hover:bg-accent"
      >
        {!hasDetail ? (
          <span className="w-3 flex-none" />
        ) : open ? (
          <ChevronDown size={12} className="flex-none text-muted-foreground" />
        ) : (
          <ChevronRight size={12} className="flex-none text-muted-foreground" />
        )}
        <Icon
          size={12}
          className={cn("flex-none", failed ? TONE_TEXT.danger : "text-muted-foreground")}
        />
        <span className="min-w-0 flex-1 truncate">{rowHeadline(segment)}</span>
        {isWrite && <AuthzChip authz={evidence.authz} />}
        {failed && (
          <XCircle
            size={12}
            className={cn("flex-none", TONE_TEXT.danger)}
            aria-label="Step failed"
          />
        )}
        {evidence.truncated && (
          <span className="flex-none text-3xs text-muted-foreground" title="Preview was truncated">
            trimmed
          </span>
        )}
      </button>

      {open && hasDetail && (
        <div className="space-y-1.5 border-t px-2 py-1.5">
          {clauses.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {clauses.map(c => (
                <span
                  key={c}
                  className={cn("rounded-full px-1.5 py-0.5 font-mono text-3xs", TONE_BADGE.info)}
                >
                  §{c}
                </span>
              ))}
            </div>
          )}
          {isWrite ? (
            // A write's payload is only half the fact. Paired with the read that
            // preceded it, the same fields say what actually changed.
            <WriteDiff
              rows={
                evidence.op === WriteOp.FunctionImport
                  ? []
                  : appliedRows(segment, baselineFor(segment, steps))
              }
              label="Applied"
              card={
                evidence.op === WriteOp.FunctionImport ? functionImportCard(segment) : undefined
              }
            />
          ) : (
            fields.length > 0 && <FieldList fields={fields} />
          )}
          {proposal && <WriteDiff rows={proposedRows(proposal, steps)} label="Proposed" />}
          {evidence.source && (
            <p className="font-mono text-3xs text-muted-foreground">
              {[evidence.source.service, evidence.source.entity, evidence.source.key]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {!isWrite && evidence.authz && (
            <p className="text-3xs text-muted-foreground">
              {evidence.authz.via_gateway
                ? `Cedar ${evidence.authz.mode === AuthzMode.Enforce ? "enforced" : "log-only"}${
                    evidence.authz.outcome ? ` · ${evidence.authz.outcome}` : " · no decision"
                  }`
                : "Cedar not evaluated — this call bypassed the Gateway"}
            </p>
          )}
          {evidence.at && (
            <p className="text-3xs text-muted-foreground">
              {new Date(evidence.at).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </li>
  )
}

function RunSteps({ trace }: { trace: AgentTrace }) {
  const [showReasoning, setShowReasoning] = useState(false)
  const { conclusion, reasoning } = splitProse(trace)
  const steps = segmentsOf(trace).filter(s => s?.type === TraceSegmentType.Tool)

  return (
    <div className="space-y-2">
      {steps.length > 0 && (
        <ol className="space-y-1">
          {steps.map((segment, i) =>
            segment.evidence ? (
              <EvidenceRow key={segment.tool_call_id ?? i} segment={segment} steps={steps} />
            ) : (
              // Pre-evidence trace. `merge_evidence` writes `status` only alongside
              // `evidence`, so this branch always reads complete — kept for the day a
              // failure is recorded without evidence, not because one is today.
              <li key={segment.tool_call_id ?? i}>
                <ToolCallDisplay
                  name={segment.tool_name ?? "unknown"}
                  args={segment.tool_input ?? ""}
                  status={segmentStatus(segment)}
                  result={segment.tool_result}
                />
              </li>
            )
          )}
        </ol>
      )}

      {conclusion && (
        <div className="border-l-2 border-primary/40 pl-2 text-xs">
          <MarkdownRenderer content={conclusion} />
        </div>
      )}

      {reasoning.length > 0 && (
        <div>
          <button
            type="button"
            aria-expanded={showReasoning}
            onClick={() => setShowReasoning(!showReasoning)}
            className="flex items-center gap-1 text-3xs text-muted-foreground transition-colors motion-reduce:transition-none hover:text-foreground"
          >
            {showReasoning ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            Reasoning ({reasoning.length} step{reasoning.length === 1 ? "" : "s"})
          </button>
          {showReasoning && (
            <div className="mt-1 space-y-1.5 border-l pl-2 text-xs text-muted-foreground">
              {reasoning.map((content, i) => (
                <MarkdownRenderer key={i} content={content} />
              ))}
            </div>
          )}
        </div>
      )}

      {steps.length === 0 && !conclusion && reasoning.length === 0 && (
        <p className="text-2xs text-muted-foreground">This run recorded no steps.</p>
      )}
    </div>
  )
}

function RunHeader({ trace }: { trace: AgentTrace }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <Clock size={10} className="flex-none text-muted-foreground" />
      {/* Dated like a collapsed run: a case opened days after it was processed would
          otherwise read a bare "14:05" as this afternoon. */}
      <span className="flex-none text-muted-foreground">
        {dateLabel(trace.timestamp)} {timeLabel(trace.timestamp)}
      </span>
      <TriggerBadge trigger={trace.trigger} />
      <OutcomeBadge outcome={trace.outcome} />
      <span className="flex-1" />
      <CopyButton trace={trace} />
    </div>
  )
}

function CollapsedRun({ trace }: { trace: AgentTrace }) {
  const [open, setOpen] = useState(false)
  const toolCount = segmentsOf(trace).filter(s => s?.type === TraceSegmentType.Tool).length

  return (
    <div className="rounded-md border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs transition-colors motion-reduce:transition-none hover:bg-accent"
      >
        {open ? (
          <ChevronDown size={12} className="flex-none text-muted-foreground" />
        ) : (
          <ChevronRight size={12} className="flex-none text-muted-foreground" />
        )}
        <span className="flex-none text-muted-foreground">
          {dateLabel(trace.timestamp)} {timeLabel(trace.timestamp)}
        </span>
        <TriggerBadge trigger={trace.trigger} />
        <OutcomeBadge outcome={trace.outcome} />
        <span className="flex-1" />
        <span className="flex-none text-3xs text-muted-foreground">
          {toolCount} step{toolCount === 1 ? "" : "s"}
        </span>
      </button>
      {open && (
        <div className="border-t px-2 py-2">
          <RunSteps trace={trace} />
        </div>
      )}
    </div>
  )
}

export function CaseTimeline({ traces }: { traces: AgentTrace[] }) {
  if (!traces || traces.length === 0) {
    return (
      <EmptyState
        className="px-0 py-6 text-left"
        message="No processing history yet."
        hint="Process this case to record its decision chain — every SAP read, every clause consulted, and every write."
      />
    )
  }

  const sorted = [...traces].sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? ""))
  const [latest, ...earlier] = sorted

  return (
    <div className="space-y-3">
      <section aria-label="Latest run" className="space-y-2">
        <RunHeader trace={latest} />
        <RunSteps trace={latest} />
      </section>

      {earlier.length > 0 && (
        <section className="space-y-1">
          {/* h4 because the only mount point supplies the h3 above it. */}
          <h4 className="text-3xs font-semibold uppercase tracking-wider text-muted-foreground">
            Earlier runs
          </h4>
          {earlier.map(t => (
            <CollapsedRun key={t.trace_id} trace={t} />
          ))}
        </section>
      )}
    </div>
  )
}
