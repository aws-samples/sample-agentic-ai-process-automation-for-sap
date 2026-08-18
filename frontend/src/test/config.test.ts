// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest"
import { readFileSync } from "fs"
import { resolve } from "path"

function parseJSONC(content: string): Record<string, unknown> {
  let cleaned = content.replace(/\/\/.*$/gm, "")
  cleaned = cleaned.replace(/\/\*[\s\S]*?\*\//g, "")
  return JSON.parse(cleaned)
}

describe("Configuration Verification Tests", () => {
  describe("vite.config.ts", () => {
    it('should have correct outDir set to "build"', () => {
      const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
      expect(viteConfig).toContain('outDir: "build"')
    })

    it("should have correct server port set to 3000", () => {
      const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
      expect(viteConfig).toContain("port: 3000")
    })

    it('should have path alias "@" configured', () => {
      const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
      expect(viteConfig).toContain("@")
      expect(viteConfig).toContain("./src")
    })

    it("should have sourcemap enabled", () => {
      const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
      expect(viteConfig).toContain("sourcemap: true")
    })

    it("should have React plugin configured", () => {
      const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
      expect(viteConfig).toContain("react()")
    })

    it("should have manual chunks configured for code splitting", () => {
      const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
      expect(viteConfig).toContain("manualChunks")
      expect(viteConfig).toContain("react-vendor")
      expect(viteConfig).toContain("ui-vendor")
      expect(viteConfig).toContain("auth-vendor")
    })
  })

  describe("tsconfig.json", () => {
    it("should have correct target set to ES2020", () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.compilerOptions.target).toBe("ES2020")
    })

    it("should have bundler module resolution", () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.compilerOptions.moduleResolution).toBe("bundler")
    })

    it("should have noEmit set to true", () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.compilerOptions.noEmit).toBe(true)
    })

    it("should have strict mode enabled", () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.compilerOptions.strict).toBe(true)
    })

    it('should have path alias "@/*" configured', () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.compilerOptions.paths).toHaveProperty("@/*")
      expect(tsconfig.compilerOptions.paths["@/*"]).toEqual(["./src/*"])
    })

    it("should have jsx set to react-jsx", () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.compilerOptions.jsx).toBe("react-jsx")
    })

    it("should include src directory", () => {
      const tsconfig = parseJSONC(readFileSync(resolve(__dirname, "../../tsconfig.json"), "utf-8"))
      expect(tsconfig.include).toContain("src")
    })
  })

  describe("package.json", () => {
    it("should have correct dev script using vite", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.scripts.dev).toBe("vite")
    })

    it("should have correct build script with tsc and vite build", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.scripts.build).toBe("tsc && vite build")
    })

    it("should have preview script", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.scripts.preview).toBe("vite preview")
    })

    it("should have vite as a dependency", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.devDependencies).toHaveProperty("vite")
    })

    it("should have @vitejs/plugin-react as a dependency", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.devDependencies).toHaveProperty("@vitejs/plugin-react")
    })

    it("should have react-router as a dependency", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.dependencies).toHaveProperty("react-router")
    })

    // v8 removed the react-router-dom re-export package; everything we use now
    // comes from react-router directly. A stray re-add would resolve a second
    // router copy alongside it.
    it("should NOT have react-router-dom as a dependency", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.dependencies).not.toHaveProperty("react-router-dom")
    })

    it("should NOT have next as a dependency", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.dependencies).not.toHaveProperty("next")
      expect(packageJson.devDependencies).not.toHaveProperty("next")
    })

    it("should NOT have eslint-config-next as a dependency", () => {
      const packageJson = JSON.parse(
        readFileSync(resolve(__dirname, "../../package.json"), "utf-8")
      )
      expect(packageJson.devDependencies).not.toHaveProperty("eslint-config-next")
    })
  })

  describe("index.html", () => {
    it("should have correct DOCTYPE and html structure", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain("<!DOCTYPE html>")
      expect(indexHtml).toContain('<html lang="en">')
    })

    it("should have root div element", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain('<div id="root"></div>')
    })

    it("should reference main.tsx as module script", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain('<script type="module" src="/src/main.tsx"></script>')
    })

    it("should have correct title", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain("<title>Agentic ERP Automation Quickstart</title>")
    })

    it("should have meta description", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain('<meta name="description"')
    })

    it("should have viewport meta tag", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"'
      )
    })

    it("should have favicon link", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain("favicon.ico")
    })

    it("should have Google Fonts preconnect links", () => {
      const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
      expect(indexHtml).toContain("fonts.googleapis.com")
      expect(indexHtml).toContain("fonts.gstatic.com")
    })
  })

  // Theme resolution is deliberately duplicated: the inline script runs before
  // first paint to avoid a flash of light, useTheme owns it from mount onwards.
  // Duplication is the point, drift is the risk — these pin the shared contract.
  describe("pre-paint theme script", () => {
    const indexHtml = () => readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
    const useTheme = () => readFileSync(resolve(__dirname, "../hooks/useTheme.ts"), "utf-8")

    it("agrees with useTheme on the storage key", () => {
      expect(indexHtml()).toContain('localStorage.getItem("ui.theme")')
      expect(useTheme()).toContain('const STORAGE_KEY = "ui.theme"')
    })

    it("agrees on the class and where it hangs", () => {
      expect(indexHtml()).toContain('document.documentElement.classList.add("dark")')
      expect(useTheme()).toContain('document.documentElement.classList.toggle("dark"')
    })

    it("runs before the app bundle, or it cannot beat first paint", () => {
      const html = indexHtml()
      expect(html.indexOf("ui.theme")).toBeLessThan(html.indexOf("/src/main.tsx"))
    })
  })

  // The type pairing is split across two files: the loader in index.html and the
  // token in globals.css. Either one alone fails silently — a missing @theme entry
  // makes `font-display` a no-op class, and a missing <link> falls back to Geist —
  // so the pairing is only real when both halves agree on the family name.
  // Compact works by re-declaring Tailwind's own scales, so it is only real if
  // `.compact` moves the variables the utilities read through. A step declared in
  // `@theme inline` gets baked into the utility and becomes unreachable — that is
  // the failure these catch, not a typo.
  describe("density scales", () => {
    const globalsCss = () => readFileSync(resolve(__dirname, "../styles/globals.css"), "utf-8")
    const compactBlock = () => {
      const css = globalsCss()
      const start = css.indexOf(".compact {")
      return css.slice(start, css.indexOf("}", start))
    }

    it("moves the spacing scale every p-*/gap-*/h-* resolves through", () => {
      expect(compactBlock()).toMatch(/--spacing:\s*0\./)
    })

    it("moves both halves of every type step, or it is only tighter margins", () => {
      const block = compactBlock()
      for (const step of ["3xs", "2xs", "xs", "sm", "base", "lg", "xl", "2xl", "3xl"]) {
        expect(block).toContain(`--text-${step}:`)
        expect(block).toContain(`--text-${step}--line-height:`)
      }
    })

    it("declares the sub-xs steps outside @theme inline so compact can move them", () => {
      const css = globalsCss()
      const inlineStart = css.indexOf("@theme inline {")
      const inlineBlock = css.slice(inlineStart, css.indexOf("}", inlineStart))
      expect(inlineBlock).not.toContain("--text-2xs")
      expect(inlineBlock).not.toContain("--text-3xs")
      expect(css).toMatch(/@theme \{[\s\S]*?--text-2xs:/)
    })
  })

  describe("type pairing", () => {
    const indexHtml = () => readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
    const globalsCss = () => readFileSync(resolve(__dirname, "../styles/globals.css"), "utf-8")

    it("loads all three faces the design uses", () => {
      const html = indexHtml()
      expect(html).toContain("family=Geist:")
      expect(html).toContain("family=Geist+Mono:")
      expect(html).toContain("family=Space+Grotesk:")
    })

    it("exposes font-display as a utility backed by the loaded face", () => {
      const css = globalsCss()
      expect(css).toContain("--font-display: var(--font-display-face)")
      expect(css).toMatch(/--font-display-face:\s*"Space Grotesk"/)
    })

    it("falls back to the body face rather than a generic sans", () => {
      // If Space Grotesk fails to load, headings should land on Geist — not on
      // whatever the browser calls sans-serif, which would change two things.
      expect(globalsCss()).toMatch(/--font-display-face:.*var\(--font-geist-sans\)/)
    })
  })
})

// Every assertion here pins the mechanism, not the number: that a token exists and
// that it derives from --spacing. A literal rem would fail on every future tuning pass.
describe("chrome sizing contract", () => {
  const globals = () => readFileSync(resolve(__dirname, "../styles/globals.css"), "utf-8")
  const rootBlock = () => {
    const css = globals()
    const start = css.indexOf(":root {")
    return css.slice(start, css.indexOf("}", start))
  }

  it("declares the three width tokens in :root", () => {
    const root = rootBlock()
    for (const token of ["--rail-w", "--dock-w", "--gutter-w"]) {
      expect(root).toContain(`${token}:`)
    }
  })

  it("derives the band height from --spacing rather than pinning a rem", () => {
    expect(rootBlock()).toMatch(/--band-h:\s*calc\(var\(--spacing\)/)
  })

  it("re-declares the panel widths in .compact, since a fixed rem would widen them", () => {
    const css = globals()
    const start = css.indexOf(".compact {")
    const compact = css.slice(start, css.indexOf("}", start))
    for (const token of ["--rail-w", "--dock-w", "--gutter-w"]) {
      expect(compact).toContain(`${token}:`)
    }
  })

  it("routes both collapsed gutters through --gutter-w, not a bare w-11", () => {
    const dock = readFileSync(resolve(__dirname, "../components/AssistantDock.tsx"), "utf-8")
    const workspace = readFileSync(resolve(__dirname, "../routes/WorkspacePage.tsx"), "utf-8")
    expect(dock).toContain("w-[var(--gutter-w)]")
    expect(workspace).toContain("w-[var(--gutter-w)]")
  })

  it("leaves no size={18} literal in the rail or dock chrome", () => {
    const rail = readFileSync(resolve(__dirname, "../components/SideRail.tsx"), "utf-8")
    const dock = readFileSync(resolve(__dirname, "../components/AssistantDock.tsx"), "utf-8")
    expect(rail).not.toMatch(/size=\{18\}/)
    expect(dock).not.toMatch(/size=\{18\}/)
  })
})

describe("createCognitoAuthConfig metadataUrl passthrough", () => {
  it("carries metadataUrl from aws-exports into the oidc config when present", async () => {
    const raw = {
      metadata_url: "https://login.microsoftonline.com/T/v2.0/.well-known/openid-configuration",
      client_id: "spa-client-id",
      redirect_uri: "https://app.example/callback",
      post_logout_redirect_uri: "https://app.example/callback",
      response_type: "code",
      scope: "email openid profile",
      automaticSilentRenew: true,
    }
    globalThis.fetch = (async () =>
      ({ ok: true, json: async () => raw }) as Response) as typeof fetch
    // getConfig caches at module scope, so reset modules to get a pristine cache.
    vi.resetModules()
    const { createCognitoAuthConfig } = await import("../lib/auth")
    const cfg = await createCognitoAuthConfig()
    expect(cfg.metadataUrl).toBe(raw.metadata_url)
    expect(cfg.client_id).toBe("spa-client-id")
  })
})
