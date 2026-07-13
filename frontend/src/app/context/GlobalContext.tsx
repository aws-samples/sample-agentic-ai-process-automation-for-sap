"use client"
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { createContext, useContext, PropsWithChildren, useState } from "react"

interface GlobalContextType {
  isLoading: boolean
  setIsLoading: (loading: boolean) => void
}

const GlobalContext = createContext<GlobalContextType | undefined>(undefined)

export function useGlobal(): GlobalContextType {
  const context = useContext(GlobalContext)
  if (context === undefined) {
    throw new Error("useGlobal must be used within a GlobalContextProvider")
  }
  return context
}

export function GlobalContextProvider({ children }: PropsWithChildren) {
  const [isLoading, setIsLoading] = useState(false)

  const value: GlobalContextType = {
    isLoading,
    setIsLoading,
  }

  return <GlobalContext.Provider value={value}>{children}</GlobalContext.Provider>
}
