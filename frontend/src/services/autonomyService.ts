// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"
import { apiFetch } from "@/lib/apiFetch"

/**
 * `/autonomy` — the trigger mode, which decides whether the poller enqueues work.
 *
 * In `auto` the poller sends every new case straight to the agent; in `manual` it
 * writes the case and stops. That is the difference between an agent that acts on
 * SAP unattended and one that waits to be asked, so it is the most consequential
 * value this UI can change.
 */

/** The two the API accepts. `null` is "the parameter has never been set". */
export type TriggerMode = "auto" | "manual"

export interface AutonomyModes {
  /**
   * Absent when SSM has no parameter — a real state, not an error, and distinct from
   * `manual`. The CDK seeds it at deploy time, so absence means something removed it.
   */
  "trigger-mode": TriggerMode | null

  /**
   * Whether this deployment has an unattended caller at all. An auth profile that does
   * not declare `autonomous` gets no poller and no `PUT /autonomy`, but the trigger
   * mode is seeded regardless — so `auto` can be stored and inert. Without this, a
   * stored `auto` reads as live unattended SAP writes on a deployment incapable of one.
   *
   * `null` is UNKNOWN (a backend predating the field), never "not capable".
   */
  "autonomous-capable"?: boolean | null
}

export async function fetchAutonomy(token: string): Promise<AutonomyModes> {
  const { apiUrl } = await getConfig()
  return apiFetch(`${apiUrl}/autonomy`, { token }, "Failed to load autonomy mode")
}

export async function saveTriggerMode(
  mode: TriggerMode,
  token: string
): Promise<Partial<AutonomyModes>> {
  const { apiUrl } = await getConfig()
  return apiFetch(
    `${apiUrl}/autonomy`,
    { token, method: "PUT", body: { "trigger-mode": mode } },
    "Failed to change autonomy mode",
    // The API answers a rejected value with `{ error }`; a bare 400 here would read
    // as "the flip failed" without saying the mode never reached SSM.
    async res => (await res.json().catch(() => ({}))).error
  )
}
