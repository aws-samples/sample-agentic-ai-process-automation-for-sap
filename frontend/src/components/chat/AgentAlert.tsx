// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { AlertTriangle, XCircle, Info } from "lucide-react"

type AlertLevel = "warning" | "error" | "info"

interface AgentAlertProps {
  level: AlertLevel
  children: React.ReactNode
}

const STYLES: Record<
  AlertLevel,
  { icon: typeof Info; border: string; bg: string; text: string; iconColor: string }
> = {
  warning: {
    icon: AlertTriangle,
    border: "border-amber-400",
    bg: "bg-amber-50",
    text: "text-amber-800",
    iconColor: "text-amber-500",
  },
  error: {
    icon: XCircle,
    border: "border-red-400",
    bg: "bg-red-50",
    text: "text-red-800",
    iconColor: "text-red-500",
  },
  info: {
    icon: Info,
    border: "border-blue-400",
    bg: "bg-blue-50",
    text: "text-blue-800",
    iconColor: "text-blue-500",
  },
}

export function AgentAlert({ level, children }: AgentAlertProps) {
  const s = STYLES[level]
  const Icon = s.icon
  return (
    <div
      className={`flex items-start gap-2 rounded-md border-l-4 ${s.border} ${s.bg} px-3 py-2 my-2 text-xs ${s.text}`}
    >
      <Icon size={14} className={`flex-none mt-0.5 ${s.iconColor}`} />
      <div className="flex-1">{children}</div>
    </div>
  )
}
