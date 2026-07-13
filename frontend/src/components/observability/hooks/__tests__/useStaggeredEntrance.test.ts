// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { useStaggeredEntrance } from "../useStaggeredEntrance"

describe("useStaggeredEntrance", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // Default: no reduced motion preference
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("returns staggered delays on first render", () => {
    const { result } = renderHook(() => useStaggeredEntrance(5, 100, 50))

    expect(result.current.getDelay(0)).toBe(100)
    expect(result.current.getDelay(1)).toBe(150)
    expect(result.current.getDelay(2)).toBe(200)
    expect(result.current.getDelay(3)).toBe(250)
    expect(result.current.getDelay(4)).toBe(300)
  })

  it("returns 0 delays after animation completes", () => {
    const { result } = renderHook(() => useStaggeredEntrance(3, 0, 40))

    // Before timeout: delays should be non-zero
    expect(result.current.getDelay(0)).toBe(0)
    expect(result.current.getDelay(1)).toBe(40)
    expect(result.current.getDelay(2)).toBe(80)

    // Advance past total duration (0 + 3 * 40 = 120ms)
    act(() => {
      vi.advanceTimersByTime(120)
    })

    // After animation: all delays should be 0
    expect(result.current.getDelay(0)).toBe(0)
    expect(result.current.getDelay(1)).toBe(0)
    expect(result.current.getDelay(2)).toBe(0)
  })

  it("hasAnimated ref starts as false and becomes true", () => {
    const { result } = renderHook(() => useStaggeredEntrance(2, 50, 30))

    expect(result.current.hasAnimated.current).toBe(false)

    // Total duration: 50 + 2 * 30 = 110ms
    act(() => {
      vi.advanceTimersByTime(110)
    })

    expect(result.current.hasAnimated.current).toBe(true)
  })

  it("returns 0 delays when prefers-reduced-motion is active", () => {
    // Override matchMedia to report reduced motion
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === "(prefers-reduced-motion: reduce)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })

    const { result } = renderHook(() => useStaggeredEntrance(5, 100, 50))

    expect(result.current.getDelay(0)).toBe(0)
    expect(result.current.getDelay(1)).toBe(0)
    expect(result.current.getDelay(4)).toBe(0)
  })

  it("uses default values for baseDelay and perItemDelay", () => {
    const { result } = renderHook(() => useStaggeredEntrance(3))

    // Defaults: baseDelay=0, perItemDelay=40
    expect(result.current.getDelay(0)).toBe(0)
    expect(result.current.getDelay(1)).toBe(40)
    expect(result.current.getDelay(2)).toBe(80)
  })
})
