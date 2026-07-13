// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useState } from "react"
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Bot,
  User,
  Webhook,
  Timer,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Unplug,
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react"
import type { AgentTrace } from "@/types/cases"
import { TraceSegmentType } from "@/types/cases"
import { MarkdownRenderer } from "@/components/chat/MarkdownRenderer"
import { ToolCallDisplay } from "@/components/chat/ToolCallDisplay"

const TRIGGER_STYLE: Record<string, { icon: typeof Bot; color: string; label: string }> = {
  manual: { icon: User, color: "bg-blue-100 text-blue-700", label: "Manual" },
  poller: { icon: Timer, color: "bg-amber-100 text-amber-700", label: "Poller" },
  "webhook-ses": { icon: Webhook, color: "bg-purple-100 text-purple-700", label: "Email" },
  webhook: { icon: Webhook, color: "bg-purple-100 text-purple-700", label: "Webhook" },
}

/** Extract a short preview string from a trace's first text segment. */
function traceSummary(trace: AgentTrace): string {
  const first = trace.segments.find(s => s.type === TraceSegmentType.Text && s.content)
  if (!first || !first.content) return ""
  const line = first.content.split("\n").find(l => l.trim()) ?? ""
  return line.length > 80 ? line.slice(0, 80) + "…" : line
}

/** Format a timestamp into a relative date label (Today, Yesterday, or date). */
function dateLabel(ts: string): string {
  const d = new Date(ts)
  const now = new Date()
  const diff = Math.floor((now.getTime() - d.getTime()) / 86_400_000)
  if (diff === 0) return "Today"
  if (diff === 1) return "Yesterday"
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function TriggerBadge({ trigger }: { trigger?: string }) {
  const style = TRIGGER_STYLE[trigger ?? ""] ?? {
    icon: Bot,
    color: "bg-muted text-foreground",
    label: trigger ?? "agent",
  }
  const Icon = style.icon
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10px] font-medium ${style.color}`}
    >
      <Icon size={10} />
      {style.label}
    </span>
  )
}

const OUTCOME_STYLE: Record<string, { icon: typeof CheckCircle2; color: string; label: string }> = {
  complete: { icon: CheckCircle2, color: "text-green-600", label: "Completed" },
  cancelled: { icon: AlertTriangle, color: "text-amber-600", label: "Stopped early" },
  error: { icon: XCircle, color: "text-red-600", label: "Error" },
  disconnected: { icon: Unplug, color: "text-muted-foreground", label: "Disconnected" },
}

function OutcomeBadge({ outcome }: { outcome?: string }) {
  if (!outcome) return null
  const style = OUTCOME_STYLE[outcome]
  if (!style) return null
  const Icon = style.icon
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[10px] font-medium ${style.color}`}
      title={style.label}
    >
      <Icon size={10} />
      {style.label}
    </span>
  )
}

/** Extract all text content from a trace for clipboard copy. */
function traceText(trace: AgentTrace): string {
  return trace.segments
    .filter(s => s.type === TraceSegmentType.Text && s.content)
    .map(s => s.content!)
    .join("\n\n")
}

function TraceActions({ trace }: { trace: AgentTrace }) {
  const [copied, setCopied] = useState(false)
  const [rated, setRated] = useState<"positive" | "negative" | null>(null)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(traceText(trace))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <div className="flex items-center gap-1 flex-none" onClick={e => e.stopPropagation()}>
      <button
        onClick={handleCopy}
        className="p-1 text-muted-foreground hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors"
        title="Copy to clipboard"
      >
        {copied ? <Check size={12} className="text-green-600" /> : <Copy size={12} />}
      </button>
      <button
        onClick={() => setRated("positive")}
        disabled={rated !== null}
        className={`p-1 rounded-md transition-colors ${rated === "positive" ? "text-green-600" : "text-muted-foreground hover:text-green-600 hover:bg-green-50"} disabled:cursor-not-allowed`}
        title="Good response"
      >
        <ThumbsUp size={12} />
      </button>
      <button
        onClick={() => setRated("negative")}
        disabled={rated !== null}
        className={`p-1 rounded-md transition-colors ${rated === "negative" ? "text-red-600" : "text-muted-foreground hover:text-red-600 hover:bg-red-50"} disabled:cursor-not-allowed`}
        title="Needs improvement"
      >
        <ThumbsDown size={12} />
      </button>
      {rated && <span className="text-[10px] text-muted-foreground ml-1">Thanks!</span>}
    </div>
  )
}

function TraceEntry({ trace, defaultOpen }: { trace: AgentTrace; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen ?? false)
  const time = new Date(trace.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
  const toolCount = trace.segments.filter(s => s.type === TraceSegmentType.Tool).length
  const summary = traceSummary(trace)

  return (
    <div className="border rounded-md overflow-hidden">
      <div
        className={`flex items-center gap-2 px-3 py-2 text-xs transition-colors ${
          open ? "bg-muted/50" : "hover:bg-accent"
        }`}
      >
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 flex-1 min-w-0 text-left"
        >
          {open ? (
            <ChevronDown size={12} className="flex-none text-muted-foreground" />
          ) : (
            <ChevronRight size={12} className="flex-none text-muted-foreground" />
          )}
          <Clock size={10} className="flex-none text-muted-foreground" />
          <span className="text-muted-foreground flex-none">{time}</span>
          <TriggerBadge trigger={trace.trigger} />
          <OutcomeBadge outcome={trace.outcome} />
          {!open && summary && (
            <span className="text-muted-foreground truncate flex-1 italic">{summary}</span>
          )}
          <span className="flex-none text-muted-foreground text-[10px]">
            {toolCount > 0 && `${toolCount} tool${toolCount > 1 ? "s" : ""} · `}
            {trace.segments.length} steps
          </span>
        </button>
        {open && <TraceActions trace={trace} />}
      </div>
      {open && (
        <div className="border-t px-3 py-2 space-y-2 bg-white max-h-[400px] overflow-auto">
          {trace.prompt && (
            <div className="text-[11px] text-muted-foreground bg-muted/50 rounded-md px-2 py-1 italic">
              {trace.prompt}
            </div>
          )}
          {trace.segments.map((seg, i) => {
            if (seg.type === TraceSegmentType.Text && seg.content) {
              return <MarkdownRenderer key={i} content={seg.content} />
            }
            if (seg.type === TraceSegmentType.Tool) {
              return (
                <ToolCallDisplay
                  key={i}
                  name={seg.tool_name ?? "unknown"}
                  args={seg.tool_input ?? ""}
                  status="complete"
                  result={seg.tool_result}
                />
              )
            }
            return null
          })}
        </div>
      )}
    </div>
  )
}

/** Renders AgentTrace entries grouped by date as collapsible accordions, most recent first. */
export function TraceViewer({ traces }: { traces: AgentTrace[] }) {
  if (!traces || traces.length === 0) {
    return <p className="text-muted-foreground text-xs">No agent traces yet.</p>
  }

  const sorted = [...traces].sort((a, b) => b.timestamp.localeCompare(a.timestamp))

  const groups: { label: string; items: AgentTrace[] }[] = []
  for (const t of sorted) {
    const lbl = dateLabel(t.timestamp)
    const last = groups[groups.length - 1]
    if (last && last.label === lbl) {
      last.items.push(t)
    } else {
      groups.push({ label: lbl, items: [t] })
    }
  }

  return (
    <div className="space-y-3">
      {groups.map(g => (
        <div key={g.label}>
          <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
            {g.label}
          </p>
          <div className="space-y-1.5">
            {g.items.map((t, i) => (
              <TraceEntry key={t.trace_id} trace={t} defaultOpen={i === 0 && g === groups[0]} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
