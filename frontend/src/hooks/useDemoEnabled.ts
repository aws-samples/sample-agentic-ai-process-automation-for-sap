// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client"
import { useEffect, useState } from "react"
import { getConfig } from "@/lib/config"

/** Which optional demo features are deployed (gates the Tickets UI and Test Data UI); both default to false until config resolves. */
export function useDemoFeatures(): { ticketing: boolean; testData: boolean } {
  const [features, setFeatures] = useState({ ticketing: false, testData: false })

  useEffect(() => {
    let active = true
    getConfig()
      .then(cfg => {
        if (active) setFeatures({ ticketing: cfg.ticketingEnabled, testData: cfg.testDataEnabled })
      })
      .catch(() => {
        if (active) setFeatures({ ticketing: false, testData: false })
      })
    return () => {
      active = false
    }
  }, [])

  return features
}
