// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { AlertTriangle, XCircle, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import { TONE_BANNER, type StatusTone } from "@/lib/statusTone"

type AlertLevel = "warning" | "error" | "info"

interface AgentAlertProps {
  level: AlertLevel
  children: React.ReactNode
}

// Colour comes from the shared tone vocabulary — this maps the alert's three
// levels onto it rather than carrying its own palette.
const LEVEL: Record<AlertLevel, { icon: typeof Info; tone: StatusTone }> = {
  warning: { icon: AlertTriangle, tone: "progress" },
  error: { icon: XCircle, tone: "danger" },
  info: { icon: Info, tone: "info" },
}

export function AgentAlert({ level, children }: AgentAlertProps) {
  const { icon: Icon, tone } = LEVEL[level]
  return (
    <div
      role={level === "error" ? "alert" : "status"}
      className={cn(
        "my-2 flex items-start gap-2 rounded-md border-l-4 px-3 py-2 text-xs",
        TONE_BANNER[tone]
      )}
    >
      <Icon size={14} className="mt-0.5 flex-none" />
      <div className="flex-1">{children}</div>
    </div>
  )
}
