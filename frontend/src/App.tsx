// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { BrowserRouter } from "react-router-dom"
import { AuthProvider } from "@/components/auth/AuthProvider"
import { GlobalContextProvider } from "@/app/context/GlobalContext"
import { NavBar } from "@/components/NavBar"
import AppRoutes from "./routes"

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <GlobalContextProvider>
          <div className="flex flex-col h-screen">
            <NavBar />
            <div className="flex-1 overflow-hidden">
              <AppRoutes />
            </div>
          </div>
        </GlobalContextProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
