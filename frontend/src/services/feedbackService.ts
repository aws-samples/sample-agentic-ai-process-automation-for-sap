// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"

export interface FeedbackPayload {
  sessionId: string
  message: string
  feedbackType: "positive" | "negative"
  comment?: string
}

export interface FeedbackResponse {
  success: boolean
  feedbackId: string
}

export async function submitFeedback(
  payload: FeedbackPayload,
  idToken: string
): Promise<FeedbackResponse> {
  const { apiUrl } = await getConfig()

  const response = await fetch(`${apiUrl}/feedback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${idToken}`,
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.error || `HTTP error! status: ${response.status}`)
  }

  return response.json()
}
