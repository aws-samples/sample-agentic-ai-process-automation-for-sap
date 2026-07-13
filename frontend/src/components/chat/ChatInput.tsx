// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"

import { FormEvent, KeyboardEvent, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Send, Square } from "lucide-react"

interface ChatInputProps {
  input: string
  setInput: (input: string) => void
  handleSubmit: (e: FormEvent) => void
  isLoading: boolean
  onStop?: () => void
  className?: string
  selectedCaseCount?: number
}

export function ChatInput({
  input,
  setInput,
  handleSubmit,
  isLoading,
  onStop,
  className = "",
  selectedCaseCount = 0,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = "0px"
      const scrollHeight = textarea.scrollHeight
      textarea.style.height = scrollHeight + "px"
    }
  }, [input])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      if (e.ctrlKey) {
        setInput(`${input}\n\n`)
        e.preventDefault()
      } else if (!e.shiftKey) {
        if (input.trim()) {
          e.preventDefault()
          handleSubmit(e as unknown as FormEvent)
        }
      }
    }
  }

  return (
    <div className={`p-4 w-full ${className}`}>
      <form
        onSubmit={handleSubmit}
        className="relative flex space-x-2 w-full items-end bg-card rounded-lg shadow-sm border p-3 focus-within:ring-1 focus-within:ring-ring transition-shadow"
      >
        {selectedCaseCount > 0 && (
          <div className="absolute -top-7 left-0 flex items-center gap-1.5 px-2.5 py-1 bg-primary text-primary-foreground text-xs font-medium rounded-t-md">
            <span>📋</span>
            <span>
              {selectedCaseCount} case{selectedCaseCount > 1 ? "s" : ""} in context
            </span>
          </div>
        )}
        <Textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message... (Ctrl+Enter for new line)"
          disabled={isLoading}
          className="flex-1 min-h-[40px] max-h-[200px] resize-none py-2"
          rows={1}
          autoFocus
        />

        {isLoading && onStop ? (
          <Button type="button" variant="destructive" onClick={onStop} className="h-10">
            <Square className="h-4 w-4 mr-2" />
            Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!input.trim() || isLoading} className="h-10">
            <Send className="h-4 w-4 mr-2" />
            Send
          </Button>
        )}
      </form>
    </div>
  )
}
