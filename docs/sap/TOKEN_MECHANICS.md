<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Token Mechanics — how the user's identity reaches SAP

Four different mechanisms can put a *user* (or a machine) identity on the SAP OData call, and they
are **not** the same thing even when they look alike on the wire. This doc is the one place the
distinction is written down, because some older docs overload the word "OBO" (see the
disambiguation note at the bottom).

## The one question that separates them

> **Does SAP see the *same* token the user logged in with, or a *new* token minted for SAP?**

That — plus *who mints the new token* — is the whole taxonomy. A subtle trap: at the **agent → MCP**
wire, "passthrough" and "OBO" can look identical (both carry the user's bearer token). They diverge
at the **MCP → SAP** wire.

| Mechanism | Flow value | Logins | SAP-facing token | Minted where | SAP trusts (SOIDC/SAML issuer) |
|---|---|---|---|---|---|
| **Token passthrough / reuse** | *(not on this stack — see below)* | 1 | the **same** inbound token, reused verbatim | nowhere; no exchange | the **same IdP** the user logged into |
| **OBO token exchange** | `ON_BEHALF_OF_TOKEN_EXCHANGE` | 1 (seamless) | a **new, SAP-scoped** token carrying the user's identity | AgentCore Identity, server-side (RFC 7523 `jwt-bearer`, outbound app creds) | the **outbound exchange app** issuer |
| **User federation (3-legged)** | `USER_FEDERATION` | 1–2 (interactive) | a **new** token from a fresh interactive authorization-code login | AgentCore drives a browser `authorization_code` flow | the IdP (OIDC) or SAP-as-SAML-SP |
| **Machine-to-machine** | `M2M` | 0 (no human) | a machine token, **no human identity** | client-credentials | app / technical user |

## Passthrough vs OBO — the distinction you actually asked about

- **Passthrough** *reuses one token*. It works **only** when SAP already trusts the exact IdP the
  user signed into (SAP SOIDC issuer == the inbound IdP), so the inbound token is already valid for
  SAP. No exchange, no second app, no second login. Simplest possible model.
- **OBO** *mints a new SAP-scoped token* by exchanging the inbound token server-side (AgentCore
  Identity, jwt-bearer). SAP validates the **exchange app's** issuer, not the raw inbound token. This
  is what you need when SAP does **not** trust the inbound IdP directly, or when you want a distinct
  SAP-audience token (tighter scoping, separate rotation) rather than spraying the raw user token to SAP.

They are genuinely different things. Passthrough is not "OBO without the exchange" — it's a *different
trust model* (one issuer end-to-end) that happens to skip the exchange because it doesn't need it.

### Why passthrough isn't a topology this stack offers

Passthrough (same Okta token for AgentCore inbound **and** the SAP call) requires a **bespoke** MCP
server that accepts the token **as a tool parameter**. This stack targets the **AWS-for-SAP MCP
server**, whose documented outbound flows are `BASIC` / `M2M` / `USER_FEDERATION` /
`ON_BEHALF_OF_TOKEN_EXCHANGE` — **passthrough is not one of them**, and the agent sends tokens in
**headers**, not tool args (tokens as tool params land in traces/model context — a security smell).
So passthrough is useful *context* for understanding the space, and its SAP-side trust facts
(SOIDC/STRUST) still apply here — but it is **not** a mode this stack builds toward. See
[OKTA_SETUP.md](./OKTA_SETUP.md) and the runbook [uf-oidc.md](./runbooks/uf-oidc.md) for those
SAP-side facts.

## Disambiguation: "OBO" in this repo

Historically some docs call `USER_FEDERATION` "**interactive OBO**" (on-behalf-of, loosely — the
agent acts on behalf of the user). That's a real English description, but it collides with the
**literal** AgentCore flow `ON_BEHALF_OF_TOKEN_EXCHANGE`. To keep it straight:

- **"OBO" (precise) = `ON_BEHALF_OF_TOKEN_EXCHANGE` only** — the server-side token *exchange*.
- **`USER_FEDERATION` = 3-legged interactive federation**. If you see "interactive OBO" in an
  older doc, read it as `USER_FEDERATION`, not the exchange flow.
- The value-space contract still holds: CDK guards key on the `obo_direct_mcp` boolean; the agent/SSM
  key on the `ON_BEHALF_OF_TOKEN_EXCHANGE` token; the literal string `"OBO"` only ever appears as the
  external stack's `authFlow` output. (See `mcp_topology.py`, `sap-mcp-stack.ts`.)

## See also

- [SAP_MCP_INTEGRATION.md](./SAP_MCP_INTEGRATION.md) — the flow/topology overview and deploy model.
- [runbooks/soidc-entra-obo.md](./runbooks/soidc-entra-obo.md) — OBO / `ON_BEHALF_OF_TOKEN_EXCHANGE` exchange (the flagship).
- [runbooks/uf-oidc.md](./runbooks/uf-oidc.md) — USER_FEDERATION (OIDC).
- [SAP_MCP_SAME_SUB_FEDERATION.md](./SAP_MCP_SAME_SUB_FEDERATION.md) — the email-join federation idea,
  the closest thing we have to a "one issuer end-to-end" trust model.
