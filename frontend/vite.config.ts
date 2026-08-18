// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import path from "path"

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },

  build: {
    outDir: "build",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // react-dom/client is listed explicitly: it is the entry main.tsx
          // actually imports, and naming only "react-dom" left the whole
          // renderer (~525 kB raw) in the app chunk instead of here.
          "react-vendor": ["react", "react-dom", "react-dom/client", "react-router"],
          "ui-vendor": [
            "@radix-ui/react-dialog",
            "@radix-ui/react-select",
            "@radix-ui/react-alert-dialog",
          ],
          "auth-vendor": ["react-oidc-context"],
        },
      },
    },
  },

  server: {
    port: 3000,
    open: true,
  },
})
