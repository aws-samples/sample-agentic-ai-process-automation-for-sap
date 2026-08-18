// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { getConfig } from "@/lib/config"
import { apiFetch } from "@/lib/apiFetch"

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
  return apiFetch(
    `${apiUrl}/feedback`,
    { token: idToken, method: "POST", body: payload },
    "HTTP error! status",
    async res => (await res.json().catch(() => ({}))).error
  )
}
