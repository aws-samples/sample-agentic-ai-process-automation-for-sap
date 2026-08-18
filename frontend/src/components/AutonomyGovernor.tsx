// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useAuth } from "react-oidc-context"
import { useFreshToken } from "@/hooks/useFreshToken"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Banner, PageLoader } from "@/components/ui/page-chrome"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { AGENT_PULSE_KEY } from "@/components/AgentHeartbeat"
import { fetchCases } from "@/services/casesService"
import { fetchAutonomy, saveTriggerMode, type TriggerMode } from "@/services/autonomyService"
import { autonomyFunnel } from "@/lib/autonomyFunnel"
import { TONE_TEXT, type StatusTone } from "@/lib/statusTone"
import { shortAge } from "@/lib/timeAgo"
import { cn } from "@/lib/utils"

/**
 * The trigger mode, with what it has actually been doing next to it.
 *
 * `auto` lets the poller invoke the agent against SAP with nobody watching. It is the
 * most consequential value in the product and, until this landed, was reachable only
 * from the CLI — so a deployment could be running unattended with no way to tell from
 * the UI it was.
 *
 * Two things make this more than a toggle. The **readout** states consequence rather
 * than configuration, and each mode is asked a different question: in `manual`, how much
 * is piling up that a human must click through; in `auto`, of what was picked up, how far
 * it got without one. The **friction** is asymmetric by design — turning auto off is one
 * click, because a mode that is hard to leave is a worse failure than one that is hard to
 * enter. Turning it on requires typing the word.
 */

/** What the operator types to arm auto. Not "yes" — it should name the thing. */
const CONFIRM_WORD = "AUTO"

/** Window for the funnel. Matches the digest's widest, where a rate is legible. */
const FUNNEL_HOURS = 24

export function AutonomyGovernor() {
  const auth = useAuth()
  const getFreshTokens = useFreshToken()
  const [confirming, setConfirming] = useState(false)
  const [typed, setTyped] = useState("")

  const modeQuery = useQuery({
    queryKey: ["autonomy"],
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchAutonomy(idToken)
    },
    enabled: auth.isAuthenticated,
  })

  // Same key the rail polls, so the readout costs no extra request.
  const casesQuery = useQuery({
    queryKey: AGENT_PULSE_KEY,
    queryFn: async () => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return fetchCases({}, idToken)
    },
    enabled: auth.isAuthenticated,
  })

  const mutation = useMutation({
    mutationFn: async (next: TriggerMode) => {
      const { idToken } = await getFreshTokens()
      if (!idToken) throw new Error("Not authenticated")
      return saveTriggerMode(next, idToken)
    },
    onSuccess: async () => {
      closeDialog()
      await modeQuery.refetch()
    },
  })

  function closeDialog() {
    setConfirming(false)
    setTyped("")
  }

  const mode = modeQuery.data?.["trigger-mode"]
  const funnel = autonomyFunnel(casesQuery.data ?? [], FUNNEL_HOURS)

  // `false` only. `undefined`/`null` is a backend that predates the field — unknown,
  // and unknown earns no new claim in either direction.
  const incapable = modeQuery.data?.["autonomous-capable"] === false
  // A stored `auto` with nothing to honour it. Not an error: the value is real, the
  // deployment just ignores it. Saying so beats hiding a misleading config.
  const inertAuto = incapable && mode === "auto"

  // Only auto is owed an outcome breakdown. Manual, unset, and incapable are all asking
  // the other question — how much is piling up — and none of them can have picked
  // anything up unattended.
  const showFunnel = mode === "auto" && !incapable

  // Named outcomes rather than a bare tally. Escalation is the modal outcome in real
  // data — 24 of 50 in the AP benchmark — so it is deliberately `attention`, not
  // `danger`: the SOP said stop and the agent stopped, which is the feature working.
  const outcomes = (
    [
      { n: funnel.landed, text: "reached SAP without a further agent run", tone: "success" },
      { n: funnel.escalated, text: "stopped for a human as the SOP requires", tone: "attention" },
      { n: funnel.inFlight, text: "still running", tone: "progress" },
      { n: funnel.failed, text: "failed", tone: "danger" },
      { n: funnel.unrecognised, text: "with an unrecognised status", tone: "neutral" },
    ] satisfies { n: number; text: string; tone: StatusTone }[]
  ).filter(o => o.n > 0)

  if (modeQuery.isLoading) return <PageLoader label="Loading autonomy mode…" />
  if (modeQuery.error instanceof Error) {
    return <Banner tone="danger">{modeQuery.error.message}</Banner>
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-display text-sm font-semibold tracking-tight">Autonomy</h2>
        <p className="max-w-2xl text-xs text-muted-foreground">
          {/* Scoped to the poller deliberately. Tickets, webhooks and this UI invoke the
              agent regardless of this mode — they are responses to something a case
              process already started, and gating them would strand cases mid-flow. */}
          Whether the poller hands new cases straight to the agent. It does not affect ticket
          replies, webhooks, or runs you start yourself.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4 rounded-md border p-4">
        <div className="grow space-y-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "rounded-sm px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wider",
                // Never destructive when there is no poller to act on it. Red here
                // would be the same overstatement this card exists to remove.
                mode === "auto" && !incapable
                  ? "bg-destructive/15 text-destructive"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {/* Absent is not `manual`. The CDK seeds this parameter, so nothing there
                  means something deleted it, and the poller's own fallback is what is
                  actually in force — worth naming rather than papering over. */}
              {mode ?? "not set"}
            </span>
            <span className="text-sm font-medium">
              {incapable
                ? "Unattended triggering is not deployed"
                : mode === "auto"
                  ? "The agent acts on new cases unattended"
                  : mode === "manual"
                    ? "The poller records new cases and waits"
                    : "No mode stored — the poller falls back to manual"}
            </span>
          </div>

          {incapable ? (
            <p className="text-xs text-muted-foreground">
              This deployment&rsquo;s auth profile has no unattended caller, so the poller is not
              running. Cases arrive only when a human or an integration asks for them.
              {inertAuto && (
                <span className="text-muted-foreground/70">
                  {" "}
                  The stored mode says auto, but nothing acts on it.
                </span>
              )}
            </p>
          ) : (
            mode === "auto" && (
              // The only link between this card and the tolerance form above it, and it
              // points rather than restating a value it does not own.
              <p className="text-xs text-muted-foreground">
                <span className="font-medium">Rung 2 of 3</span> — cases still stop at every SOP
                escalation. Widening those tolerances is the Tolerances section above.
              </p>
            )
          )}

          {/* Consequence, not configuration — and each mode is owed a different one. A
              count of invocations is evidence of scheduling: the poller runs on its
              timer in either mode. Where cases *ended up* is the only thing on this card
              that a wrong setting cannot also claim. */}
          <p className="text-xs text-muted-foreground">
            {casesQuery.isLoading ? (
              showFunnel ? (
                "Counting what the agent picked up…"
              ) : (
                "Counting cases waiting…"
              )
            ) : showFunnel ? (
              <>
                <span className="font-medium text-foreground">
                  {funnel.started === 0
                    ? `Nothing picked up in the last ${FUNNEL_HOURS}h.`
                    : `${funnel.started} case${funnel.started === 1 ? "" : "s"} picked up in the last ${FUNNEL_HOURS}h.`}
                </span>{" "}
                {outcomes.map((o, i) => (
                  <span key={o.text}>
                    {i > 0 && " · "}
                    <span className={cn("font-medium", TONE_TEXT[o.tone])}>{o.n}</span> {o.text}
                  </span>
                ))}
                {outcomes.length > 0 && "."}
                {/* Auto is on, the poller is finding cases, and none of them are being
                    handed over. The one diagnostic a count of runs cannot show. */}
                {funnel.started === 0 && funnel.backlog > 0 && (
                  <span className="text-foreground">
                    {" "}
                    {funnel.backlog} case{funnel.backlog === 1 ? " is" : "s are"} waiting in{" "}
                    <span className="font-medium">detected</span> — auto is on but nothing is being
                    enqueued.
                  </span>
                )}
                {funnel.latest && ` Most recently ${shortAge(funnel.latest)} ago.`}
              </>
            ) : (
              <>
                <span className="font-medium text-foreground">
                  {funnel.backlog === 0
                    ? "No cases waiting."
                    : `${funnel.backlog} case${funnel.backlog === 1 ? "" : "s"} waiting.`}
                </span>{" "}
                {funnel.backlog > 0 &&
                  "Detected by the poller, none started. In manual, each needs a human to click Process."}
              </>
            )}
            {funnel.partial && !casesQuery.isLoading && showFunnel && (
              <span className="text-muted-foreground/70">
                {" "}
                At least this many — some cases carry no attributable trace history.
              </span>
            )}
          </p>
        </div>

        {incapable ? (
          // PUT /autonomy is only mounted when the queue exists, so this control would
          // 405. A button that cannot work should not look like one that can.
          <div className="text-right">
            <Button variant="destructive" disabled>
              Switch to auto
            </Button>
            <p className="mt-1 text-2xs text-muted-foreground">
              Requires an autonomous auth profile
            </p>
          </div>
        ) : mode === "auto" ? (
          // Leaving auto is deliberately frictionless: the friction belongs on the way in.
          <Button
            variant="outline"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate("manual")}
          >
            {mutation.isPending ? "Switching…" : "Switch to manual"}
          </Button>
        ) : (
          <Button variant="destructive" onClick={() => setConfirming(true)}>
            Switch to auto
          </Button>
        )}
      </div>

      {mutation.error instanceof Error && <Banner tone="danger">{mutation.error.message}</Banner>}

      <AlertDialog open={confirming} onOpenChange={open => !open && closeDialog()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Let the agent act unattended?</AlertDialogTitle>
            <AlertDialogDescription>
              In auto, the poller invokes the agent on every new case it finds. The agent follows
              its SOPs and writes to SAP without waiting to be asked. Cases that exceed a tolerance
              still escalate to a human; everything within tolerance is handled and posted.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div>
            <label htmlFor="confirm-auto" className="mb-1 block text-sm font-medium">
              Type <span className="font-mono font-semibold">{CONFIRM_WORD}</span> to confirm
            </label>
            {/* Typing the word rather than clicking twice. A second confirm button is
                still one gesture away from the first; this cannot be hit by accident. */}
            <Input
              id="confirm-auto"
              autoComplete="off"
              value={typed}
              onChange={e => setTyped(e.target.value)}
            />
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={typed !== CONFIRM_WORD || mutation.isPending}
              onClick={() => mutation.mutate("auto")}
            >
              {mutation.isPending ? "Switching…" : "Switch to auto"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
