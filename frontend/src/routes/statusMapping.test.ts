// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { healthTone } from "./AnalyticsDashboard"
import { varianceMeta } from "./TestDataPage"

const LABELS = { match: "Qty match", over: "Qty over", under: "Qty short" }

describe("varianceMeta", () => {
  it("reads over-invoiced as danger and under-invoiced as merely notable", () => {
    expect(varianceMeta(0, LABELS)).toEqual({ label: "Qty match", tone: "success" })
    expect(varianceMeta(2500, LABELS)).toEqual({ label: "Qty over", tone: "danger" })
    expect(varianceMeta(-2500, LABELS)).toEqual({ label: "Qty short", tone: "progress" })
  })
})

describe("healthTone", () => {
  it("folds both vocabularies onto the same three outcomes", () => {
    expect(healthTone("healthy")).toBe("success")
    expect(healthTone("OK")).toBe("success")
    expect(healthTone("error")).toBe("danger")
    expect(healthTone("ALARM")).toBe("danger")
  })

  // Absent data is not good news — an unrecognised state must never read green.
  it("defaults an unknown state to neutral", () => {
    expect(healthTone("INSUFFICIENT_DATA")).toBe("neutral")
    expect(healthTone("something-new-from-the-api")).toBe("neutral")
  })
})
