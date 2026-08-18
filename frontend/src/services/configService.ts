// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"
import { apiFetch } from "@/lib/apiFetch"

/**
 * `/config` — the contacts and tolerance constants the SOP corpus cites.
 *
 * Distinct from `lib/config`'s `getConfig()`, which reads the deploy-time frontend
 * config (API URLs, Cognito IDs). This one edits values the agent reads at runtime.
 */

export interface ConfigValues {
  /** config.yaml key → address. The SOP writes `{{CONTACT_<KEY>}}`. */
  contacts: Record<string, string>
  /** skill_id → {SYMBOL: value}, from each skill's `constants` block. */
  constants: Record<string, Record<string, number>>
}

export interface RuntimeConfig {
  /** What the current deployment shipped — the value an override reverts to. */
  defaults: ConfigValues
  /** Only edited symbols appear here, which is what lets the UI mark a difference. */
  overrides: ConfigValues
  /** SYMBOL → [low, high], so the form cannot offer a value the API would reject. */
  bounds: Record<string, [number, number]>
}

/** `null` deletes an override, reverting the symbol to its deployed default. */
export interface ConfigPatch {
  contacts?: Record<string, string | null>
  constants?: Record<string, Record<string, number | null>>
}

export interface SaveConfigResult {
  updated: number
  updated_by: string
}

export async function fetchRuntimeConfig(token: string): Promise<RuntimeConfig> {
  const { apiUrl } = await getConfig()
  return apiFetch(`${apiUrl}/config`, { token }, "Failed to load configuration")
}

export async function saveRuntimeConfig(
  patch: ConfigPatch,
  token: string
): Promise<SaveConfigResult> {
  const { apiUrl } = await getConfig()
  return apiFetch(
    `${apiUrl}/config`,
    { token, method: "PUT", body: patch },
    "Failed to save configuration",
    // A rejected write names every field it refused. Surfacing only the status
    // would leave the operator guessing which row the API disagreed with.
    async res => {
      const body = await res.json().catch(() => ({}))
      const details = Array.isArray(body.details) ? body.details.join("; ") : ""
      return details || body.error
    }
  )
}
