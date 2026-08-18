// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useSyncExternalStore } from "react"
import type { Message } from "@/components/chat/types"

/**
 * The interactive conversation's messages, held outside React state.
 *
 * A module store rather than `useState` in the shell because the shell is a layout
 * route: state there re-renders the outlet context, so every streamed token used to
 * re-render the routed page and its case list. Only the assistant reads the
 * transcript, and `useTranscript` subscribes it directly.
 *
 * Never persisted. Messages carry SAP tool results — PO numbers, amounts, vendor
 * data — and localStorage would leak them across logout on a shared machine. The
 * sign-in flow uses a popup, so the tab never unloads and this survives it.
 */

const EMPTY: Message[] = []

let messages: Message[] = EMPTY
const listeners = new Set<() => void>()

export function getTranscript(): Message[] {
  return messages
}

/** Replace the transcript. Accepts an updater so callers can append without reading. */
export function setTranscript(next: Message[] | ((prev: Message[]) => Message[])): void {
  const resolved = typeof next === "function" ? next(messages) : next
  if (resolved === messages) return
  messages = resolved
  for (const listener of listeners) listener()
}

export function subscribeTranscript(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useTranscript(): Message[] {
  return useSyncExternalStore(subscribeTranscript, getTranscript)
}

/**
 * Drop the conversation. Called on sign-out alongside the rest of the operator's
 * working context, and on Clear.
 */
export function clearTranscript(): void {
  setTranscript(EMPTY)
}
