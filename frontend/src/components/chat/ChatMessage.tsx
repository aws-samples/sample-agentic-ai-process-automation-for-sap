// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { useState } from "react"
import { ThumbsUp, ThumbsDown, Copy, Check } from "lucide-react"
import { Message } from "./types"
import { FeedbackDialog } from "./FeedbackDialog"
import { getToolRenderer } from "@/hooks/useToolRenderer"
import { MarkdownRenderer } from "./MarkdownRenderer"
import { AgentAlert } from "./AgentAlert"

interface ChatMessageProps {
  message: Message
  sessionId: string
  onFeedbackSubmit: (feedbackType: "positive" | "negative", comment: string) => Promise<void>
}

export function ChatMessage({
  message,
  sessionId: _sessionId, // eslint-disable-line @typescript-eslint/no-unused-vars
  onFeedbackSubmit,
}: ChatMessageProps) {
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [selectedFeedbackType, setSelectedFeedbackType] = useState<"positive" | "negative">(
    "positive"
  )
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API can fail if page is not focused or permissions denied
    }
  }

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const handleFeedbackClick = (type: "positive" | "negative") => {
    setSelectedFeedbackType(type)
    setIsDialogOpen(true)
  }

  const handleFeedbackSubmit = async (comment: string) => {
    await onFeedbackSubmit(selectedFeedbackType, comment)
    setFeedbackSubmitted(true)
  }

  const renderAssistantContent = () => {
    // If segments exist, render them in order (interleaved text + tools)
    if (message.segments && message.segments.length > 0) {
      return message.segments.map((seg, i) => {
        if (seg.type === "text") {
          const trimmed = seg.content.trim()
          if (trimmed.startsWith("⚠️")) {
            return (
              <AgentAlert key={i} level="warning">
                {trimmed.replace(/^⚠️\s*/, "")}
              </AgentAlert>
            )
          }
          if (trimmed.startsWith("❌")) {
            return (
              <AgentAlert key={i} level="error">
                {trimmed.replace(/^❌\s*/, "")}
              </AgentAlert>
            )
          }
          return <MarkdownRenderer key={i} content={seg.content} />
        }
        const render = getToolRenderer(seg.toolCall.name)
        if (!render) return null
        return (
          <div key={seg.toolCall.toolUseId} className="my-1">
            {render({
              name: seg.toolCall.name,
              args: seg.toolCall.input,
              status: seg.toolCall.status,
              result: seg.toolCall.result,
            })}
          </div>
        )
      })
    }
    const trimmed = message.content.trim()
    if (trimmed.startsWith("⚠️")) {
      return <AgentAlert level="warning">{trimmed.replace(/^⚠️\s*/, "")}</AgentAlert>
    }
    if (trimmed.startsWith("❌")) {
      return <AgentAlert level="error">{trimmed.replace(/^❌\s*/, "")}</AgentAlert>
    }
    return <MarkdownRenderer content={message.content} />
  }

  return (
    <div className={`flex flex-col ${message.role === "user" ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[80%] break-words text-sm ${
          message.role === "user"
            ? "p-3 rounded-lg bg-primary text-primary-foreground rounded-br-none whitespace-pre-wrap"
            : "text-foreground"
        }`}
      >
        {message.role === "assistant" ? renderAssistantContent() : message.content}
      </div>

      <div className="flex items-center gap-2 mt-1 px-1">
        <div className="text-xs text-muted-foreground">{formatTime(message.timestamp)}</div>

        {message.role === "assistant" && message.content && (
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={handleCopy}
              className="p-1 text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
              aria-label="Copy message"
              title="Copy to clipboard"
            >
              {copied ? <Check size={14} className="text-green-600" /> : <Copy size={14} />}
            </button>
            <button
              onClick={() => handleFeedbackClick("positive")}
              disabled={feedbackSubmitted}
              className="p-1 text-muted-foreground hover:text-green-600 hover:bg-green-50 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Positive feedback"
              title="Good response"
            >
              <ThumbsUp size={14} />
            </button>
            <button
              onClick={() => handleFeedbackClick("negative")}
              disabled={feedbackSubmitted}
              className="p-1 text-muted-foreground hover:text-red-600 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Negative feedback"
              title="Bad response"
            >
              <ThumbsDown size={14} />
            </button>
            {feedbackSubmitted && (
              <span className="text-xs text-muted-foreground ml-1">Thanks for your feedback!</span>
            )}
          </div>
        )}
      </div>

      <FeedbackDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        onSubmit={handleFeedbackSubmit}
        feedbackType={selectedFeedbackType}
      />
    </div>
  )
}
