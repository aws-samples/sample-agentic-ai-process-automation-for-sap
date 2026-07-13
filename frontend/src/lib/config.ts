// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared runtime configuration loaded from /aws-exports.json.
 * Single fetch, cached for the lifetime of the app.
 */

export interface AppConfig {
  authority: string
  /** External-IdP discovery URL (mutually exclusive with a Cognito authority). */
  metadataUrl?: string
  client_id: string
  redirect_uri: string
  post_logout_redirect_uri: string
  response_type: string
  scope: string
  automaticSilentRenew: boolean
  agentRuntimeArn: string
  awsRegion: string
  apiUrl: string
  feedbackApiUrl: string
  demoApiUrl?: string
  /** True when the ticketing/ITSM stand-in is deployed. Gates the Tickets UI. */
  ticketingEnabled: boolean
  /** True when the test-data stack is deployed. Gates the Test Data UI. */
  testDataEnabled: boolean
  agentPattern: string
}

let cached: AppConfig | null = null
let pending: Promise<AppConfig> | null = null

export function getConfig(): Promise<AppConfig> {
  if (cached) return Promise.resolve(cached)
  if (pending) return pending

  pending = fetch("/aws-exports.json")
    .then(res => {
      if (!res.ok) throw new Error(`Failed to load aws-exports.json: ${res.status}`)
      return res.json()
    })
    .then(raw => {
      // apiUrl falls back to feedbackApiUrl (same API Gateway) for backwards compat
      const base = (raw.apiUrl || raw.feedbackApiUrl || "").replace(/\/+$/, "")
      // Ticketing (backend-hosted /tickets) and test-data (separate demo stack)
      // are independent. Ticketing is signalled by ticketingEnabled; test-data by
      // demoApiUrl. Legacy demoEnabled turns both on for backwards compatibility.
      const ticketingEnabled = Boolean(raw.ticketingEnabled ?? raw.demoEnabled)
      const testDataEnabled = Boolean(raw.testDataEnabled ?? raw.demoEnabled ?? raw.demoApiUrl)
      cached = {
        ...raw,
        apiUrl: base,
        ticketingEnabled,
        testDataEnabled,
        metadataUrl: raw.metadata_url ?? raw.metadataUrl,
      }
      return cached!
    })

  return pending
}
