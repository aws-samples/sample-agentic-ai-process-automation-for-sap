// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useRef, useEffect } from "react"

/**
 * Hook that provides staggered entrance animation delays for a list of items.
 *
 * On first render, `getDelay(index)` returns `baseDelay + index * perItemDelay`
 * so each item can animate in with a stagger effect. On subsequent renders
 * (e.g. auto-refresh), it returns 0 so values update in-place without replaying
 * entrance animations.
 *
 * Respects `prefers-reduced-motion` — when the user prefers reduced motion,
 * all delays are 0 regardless of render count.
 *
 * @param itemCount - Number of items to animate (used to compute total animation duration)
 * @param baseDelay - Delay in ms before the first item animates (default 0)
 * @param perItemDelay - Delay in ms between each successive item (default 40)
 */
export function useStaggeredEntrance(
  itemCount: number,
  baseDelay: number = 0,
  perItemDelay: number = 40
) {
  const hasAnimated = useRef(false)

  // Check prefers-reduced-motion once on mount
  const prefersReducedMotion = useRef(false)
  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia) {
      prefersReducedMotion.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    }
  }, [])

  // Flip to animated only after the full stagger duration elapses, so later renders skip the entrance animation.
  useEffect(() => {
    if (hasAnimated.current) return
    const totalDuration = baseDelay + itemCount * perItemDelay
    const timer = setTimeout(() => {
      hasAnimated.current = true
    }, totalDuration)
    return () => clearTimeout(timer)
  }, [itemCount, baseDelay, perItemDelay])

  /**
   * Returns the animation delay in ms for the item at the given index.
   * Returns 0 if animations have already played or reduced motion is preferred.
   */
  const getDelay = (index: number): number => {
    if (hasAnimated.current || prefersReducedMotion.current) {
      return 0
    }
    return baseDelay + index * perItemDelay
  }

  return { hasAnimated, getDelay }
}
