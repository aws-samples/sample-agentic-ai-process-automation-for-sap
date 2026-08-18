// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Outlet, useOutletContext } from "react-router"
import { SideRail } from "@/components/SideRail"
import { AssistantDock } from "@/components/AssistantDock"
import { usePanelCollapsed } from "@/hooks/usePanelCollapsed"
import { useAgentChat, type AgentChat } from "@/hooks/useAgentChat"

/**
 * Root layout: the rail owns the left gutter, the assistant owns the right, and the
 * matched route takes what is between them.
 *
 * The conversation is owned here rather than by a page because a run has to survive
 * navigation — a page that owned it would tear the stream down on every route change.
 * `<Outlet context>` hands it to the routed page; `useAssistant()` reads it there.
 *
 * min-w-0 lets Allotment's flex children shrink instead of overflowing.
 */
export function AppShell() {
  const chat = useAgentChat()
  const { collapsed, toggle } = usePanelCollapsed("ui.dock.collapsed", "j")

  return (
    <div className="flex h-screen">
      <SideRail />
      {/* Outlet stays the direct child of <main>: Workspace's full-bleed exemption is
          asserted by that shape, and a wrapper here would silently break it. */}
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet context={chat} />
      </main>
      <AssistantDock chat={chat} collapsed={collapsed} onToggleCollapse={toggle} />
    </div>
  )
}

/**
 * Frame for the dashboard routes: a full-height column whose header stays put
 * while the body scrolls. Owning it here is what stops each page re-deciding
 * its own outer box. Workspace opts out — see the route config.
 *
 * Forwards the outlet context: a bare `<Outlet />` would publish `undefined` and the
 * pages below this frame would lose the assistant.
 */
export function PageFrame() {
  const chat = useOutletContext<AgentChat>()
  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden">
      <Outlet context={chat} />
    </div>
  )
}
