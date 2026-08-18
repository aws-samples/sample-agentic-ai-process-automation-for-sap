// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { MarkdownRenderer } from "./MarkdownRenderer"

/**
 * Covers the async syntax highlighter. Grammars now load on demand instead of
 * being bundled eagerly, so highlighting arrives a tick after first paint and a
 * broken loader would fail silently — the code text still renders either way.
 */
describe("MarkdownRenderer", () => {
  it("highlights a fenced block once the grammar resolves", async () => {
    render(<MarkdownRenderer content={"```python\nx = 1\n```"} />)

    // Language label and code text are there synchronously.
    expect(screen.getByText("python")).toBeTruthy()

    // Prism token spans only appear after the grammar chunk loads.
    await waitFor(() => {
      const tokens = document.querySelectorAll("code span.token")
      expect(tokens.length).toBeGreaterThan(0)
    })
  })

  it("renders an unsupported language as plain text", async () => {
    render(<MarkdownRenderer content={"```wingdingscript\nfoo\n```"} />)
    // The highlighter normalizes unknown languages to `text` rather than throwing.
    await waitFor(() => expect(screen.getByText(/foo/)).toBeTruthy())
  })

  it("opens external prose links in a new tab", () => {
    render(<MarkdownRenderer content="[docs](https://example.com)" />)
    const link = screen.getByRole("link", { name: "docs" })
    expect(link.getAttribute("target")).toBe("_blank")
    expect(link.getAttribute("rel")).toBe("noopener noreferrer")
  })

  it("leaves relative links in the same tab", () => {
    render(<MarkdownRenderer content="[case](/cases/123)" />)
    expect(screen.getByRole("link", { name: "case" }).getAttribute("target")).toBeNull()
  })

  it("closes an unterminated code fence while streaming", () => {
    render(<MarkdownRenderer content={"```json\n{"} />)
    expect(screen.getByText("json")).toBeTruthy()
  })
})
