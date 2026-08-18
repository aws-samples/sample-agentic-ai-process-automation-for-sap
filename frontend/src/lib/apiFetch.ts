// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface ApiFetchInit extends Omit<RequestInit, "body"> {
  token: string
  body?: unknown
}

/**
 * Fetch JSON from the API with the bearer token attached.
 *
 * Throws `${errorMessage}: ${status}` on a non-2xx response by default. Pass
 * `parseError` to extract a more specific message from the error body first
 * (e.g. a JSON `{ error }` field or raw text) — used where the backend returns
 * detail worth surfacing verbatim instead of just a status code.
 */
export async function apiFetch<T>(
  url: string,
  { token, body, headers, ...init }: ApiFetchInit,
  errorMessage: string,
  parseError?: (res: Response) => Promise<string | undefined>
): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = parseError ? await parseError(res).catch(() => undefined) : undefined
    throw new Error(detail || `${errorMessage}: ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
