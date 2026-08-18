// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { RefObject } from "react"
import { Message } from "./types"
import { ChatMessage } from "./ChatMessage"

interface ChatMessagesProps {
  messages: Message[]
  messagesEndRef: RefObject<HTMLDivElement | null>
  sessionId: string
  onFeedbackSubmit: (
    messageContent: string,
    feedbackType: "positive" | "negative",
    comment: string
  ) => Promise<void>
}

export function ChatMessages({
  messages,
  messagesEndRef,
  sessionId,
  onFeedbackSubmit,
}: ChatMessagesProps) {
  return (
    <div
      className={`h-full p-4 space-y-4 w-full ${
        messages.length > 0 ? "overflow-y-auto" : "overflow-hidden"
      }`}
    >
      {messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-muted-foreground">
          Start a new conversation
        </div>
      ) : (
        messages.map((message, index) => (
          <ChatMessage
            key={message.id ?? index}
            message={message}
            sessionId={sessionId}
            onFeedbackSubmit={async (feedbackType, comment) => {
              await onFeedbackSubmit(message.content, feedbackType, comment)
            }}
          />
        ))
      )}
      <div ref={messagesEndRef} />
    </div>
  )
}
