// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef } from "react"
import type { FormEvent } from "react"
import { PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react"
import { ICON_CHROME } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Banner } from "@/components/ui/page-chrome"
import { ChatInput } from "@/components/chat/ChatInput"
import { ChatMessages } from "@/components/chat/ChatMessages"
import { useTranscript } from "@/lib/transcript"
import type { AgentChat } from "@/hooks/useAgentChat"

/**
 * The assistant, docked on the shell's trailing edge and present on every route.
 *
 * It is a panel rather than a page because the case is the subject and the
 * conversation is a way of asking about it — so it sits beside whatever the
 * operator is reading, and the case it is talking about comes from the URL rather
 * than from a page handing it over.
 *
 * The transcript is subscribed here rather than arriving on `chat`, so a streamed
 * token re-renders this panel and nothing else. See `lib/transcript`.
 */

/**
 * The panel's one collapse control, on its leading edge in both states.
 *
 * A full-height edge rather than a corner button: it is the border the hand is
 * already travelling to, it cannot move when the header's contents change, and the
 * same gesture reopens the cases rail (`WorkspacePage.tsx:141`). Two controls in two
 * corners was the defect — the operator had to learn a different target per state.
 *
 * A `<button>` and not a bare div with a click handler, so it is reachable by keyboard
 * and announces its state; the chevron only appears on hover or focus, since a
 * permanent one on a full-height edge reads as a scrollbar.
 */
function CollapseEdge({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const Icon = collapsed ? PanelRightOpen : PanelRightClose
  const label = collapsed ? "Open the assistant" : "Collapse the assistant"
  return (
    <button
      onClick={onToggle}
      title={`${label} (⌘J)`}
      aria-label={label}
      aria-expanded={!collapsed}
      className="group absolute inset-y-0 left-0 z-10 flex w-1.5 items-center justify-center outline-none transition-colors motion-reduce:transition-none hover:w-3 hover:bg-accent focus-visible:w-3 focus-visible:bg-accent"
    >
      <Icon
        size={ICON_CHROME}
        className="pointer-events-none opacity-0 transition-opacity motion-reduce:transition-none group-hover:opacity-100 group-focus-visible:opacity-100"
      />
    </button>
  )
}
export function AssistantDock({
  chat,
  collapsed,
  onToggleCollapse,
}: {
  chat: AgentChat
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messages = useTranscript()

  // Only meaningful while the panel is open: scrollIntoView on a hidden element
  // scrolls the page instead.
  useEffect(() => {
    if (!collapsed) messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, collapsed])

  if (collapsed) {
    return (
      <div className="relative flex w-[var(--gutter-w)] flex-none flex-col items-center border-l py-2">
        <CollapseEdge collapsed onToggle={onToggleCollapse} />
        <button
          onClick={onToggleCollapse}
          className="flex-1 text-xs font-medium tracking-wide text-muted-foreground transition-colors motion-reduce:transition-none hover:text-foreground [writing-mode:vertical-rl]"
          title="Open the assistant (⌘J)"
        >
          Assistant
        </button>
      </div>
    )
  }

  const hasMessages = messages.length > 0
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    void chat.send(chat.input)
  }

  return (
    <aside
      aria-label="Assistant"
      className="relative flex w-[var(--dock-w)] flex-none flex-col border-l"
    >
      <CollapseEdge collapsed={false} onToggle={onToggleCollapse} />
      <div className="flex-none border-b px-3 py-2">
        <div className="flex min-h-7 items-center justify-between gap-2">
          <h2 className="min-w-0 truncate text-sm font-semibold">
            Assistant
            {/* Names the case so the operator can see what "this case" means to the
                agent without asking it, and can tell when nothing is in context. */}
            {chat.caseId && (
              <span className="ml-1.5 font-mono text-2xs font-normal text-muted-foreground">
                {chat.caseId}
              </span>
            )}
            {chat.contextCaseCount > 0 && (
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                ({chat.contextCaseCount} selected)
              </span>
            )}
          </h2>
          {hasMessages && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 flex-none text-xs"
              onClick={chat.clear}
            >
              Clear
            </Button>
          )}
        </div>
      </div>

      {chat.error && (
        <Banner tone="danger" className="mx-2 mt-1 p-2 text-xs">
          {chat.error}
        </Banner>
      )}

      {!hasMessages ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-3">
          <div className="animate-rise-in flex max-w-sm flex-col items-center gap-4 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <Sparkles size={20} />
            </span>
            <div>
              <h3 className="font-display text-lg font-semibold tracking-tight text-foreground">
                Ready when you are
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {chat.caseId
                  ? "Ask about this case, or select cases and click Process."
                  : "Select cases and click Process, or just ask the agent a question below."}
              </p>
            </div>
          </div>
          <div className="w-full">
            <ChatInput
              input={chat.input}
              setInput={chat.setInput}
              handleSubmit={handleSubmit}
              isLoading={chat.isLoading}
              onStop={chat.stop}
              selectedCaseCount={chat.contextCaseCount}
            />
          </div>
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-hidden">
            <ChatMessages
              messages={messages}
              messagesEndRef={messagesEndRef}
              sessionId={chat.sessionId}
              onFeedbackSubmit={chat.submitMessageFeedback}
            />
          </div>
          <div className="flex-none">
            <ChatInput
              input={chat.input}
              setInput={chat.setInput}
              handleSubmit={handleSubmit}
              isLoading={chat.isLoading}
              onStop={chat.stop}
              selectedCaseCount={chat.contextCaseCount}
            />
          </div>
        </>
      )}
    </aside>
  )
}
