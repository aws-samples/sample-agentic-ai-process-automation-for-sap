<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Okta Setup — direct-Okta frontend + Okta inbound

Okta is **Entra's sibling** on the same generic auth machinery — the inbound JWT authorizer and the
direct-IdP frontend are issuer-*parameterized*, not per-IdP. There is **no Okta-specific code**; this
doc is the config reference for wiring a real Okta org into the Okta profiles.

Two profiles select the Okta axes, differing only in the outbound leg:

| Profile | Outbound | Use it to |
|---|---|---|
| `okta-basic` | `basic` (GA) | Prove the **Okta axes** (`direct-okta` frontend + `okta` inbound) end-to-end. SAP identity is the technical user, so nothing depends on a blocked outbound. **Start here** — both axes were cleared this way, so it is CDK-supported (unverified: its outbound never carries a user to SAP). |
| `okta-userfed` | `user-federation` (stub) | Add per-user SAP identity. Blocked upstream — see [`SAP_MCP_USER_FEDERATION.md`](SAP_MCP_USER_FEDERATION.md). |

`okta-basic` exists because `user-federation` cannot currently complete: AgentCore Identity never
redeems the Okta authorization code in its 3LO vault. That blocker is on the **outbound** leg only,
so it does not have to gate proving the inbound and frontend axes.

> **STATUS.** The Okta→SOIDC→SAP token round-trip was **live-verified** against an S/4HANA 2023
> system (standalone-MCP variant): Okta custom authorization server, SOIDC email mapping on `sub`,
> `Authorization: Bearer <access_token>` → OData **HTTP 200** as the mapped user. The AWS-side
> (emit/resolve) is built + unit-tested; the *repo-topology* path (Gateway/external MCP) is not yet
> live.
>
> **A trial org can stop being administrable** — if its Admin API mints only `*.read` scopes and
> every `*.manage` returns `consent_required`, its app, audience, and claim config can no longer be
> changed and the tenant has to be rebuilt. The verified *mechanism* survives that; the tenant does
> not. Build your own org per "Building a new Okta org from the console" below, then register the
> SAP-side trust per O5.
>
> **The two AWS-side Okta axes are closed independently of the SAP leg:** a login through the
> deployed SPA issues an `id_token` the deployed authorizer accepts and the request reaches the
> backend. That clears `frontend: direct-okta` + `inbound: okta` and is why `okta-basic` is
> CDK-supported. It says nothing about the SAP leg above — the two are independent, and `okta-basic`
> reaches SAP as a technical user.
>
> **Two non-obvious SAP-side gotchas that gated the round-trip (both cost hours):**
> 1. **ICF logon-procedure ORDER on the OData node.** SAP has two independent OIDC modes —
>    `OIDC Bearer Token` (Bearer passthrough, what we use) and `OIDC Logon` (interactive redirect).
>    ICF tries the node's procedures *in list order*; if `OIDC Logon` precedes `OIDC Bearer Token`,
>    a headless Bearer call matches the interactive procedure first and 401s with HTML
>    `Anmeldung fehlgeschlagen`. Fix: remove `OIDC Logon` from the node (or order Bearer first).
>    SOIDC's own **OpenID Connect Mode Configuration** gates the same thing one level up — enable
>    *Token Forwarding (OIDC Bearer)* and leave *Interactive (OIDC Logon)* off, so the interactive
>    procedure is never offered. Check the node anyway; the provider setting does not retract a
>    procedure already attached there.
> 2. **Audience must equal SAP's own client ID.** SAP rejects any token whose `aud` doesn't contain
>    the SOIDC-configured client ID, regardless of eval mode. `aud` is written by Okta — set
>    **Okta AS → Settings → Audience = `<your-okta-app-client-id>`** (Okta's default `api://default`
>    will NOT match). Fix is on the IdP, not SAP.

## The profile

Both profiles are `frontend: direct-okta` · `inbound: okta` · `mode: [live]`, and differ only in
`outbound` (`auth-profiles.yaml`). The frontend signs the user in against Okta directly; the backend
authorizer validates the Okta-issued JWT. `okta-basic` then reaches SAP as the technical user;
`okta-userfed` uses the shared USER_FEDERATION flow (see
[`SAP_MCP_USER_FEDERATION.md`](SAP_MCP_USER_FEDERATION.md)).

## Building a new Okta org from the console

The Admin API cannot do this for you unless the org's service app has `*.manage` scopes consented —
a fresh org does not. These are the console click-paths, in dependency order. Collect the four values
in **What you must supply** as you go.

O0 wires up the Okta MCP so later steps are partly scriptable; O1–O3 are irreducibly console work
(no MCP tool covers authorization servers). Start at O1 if you would rather not run an MCP at all.

### O0. Re-point the Okta MCP server at the new org

Optional but it pays for itself: with `okta.apps.manage` granted, the MCP creates the O2 app and
reads the System Log, which is where a SAP 401 is actually diagnosed. It is a *management* client —
separate from the O2 app the SPA and SAP use, and it plays no part in the auth flow under test.

```bash
test-scripts/rewire-okta-mcp.sh https://<new-org>.okta.com <mcp-app-client-id>
# restart Claude Code, use any Okta tool to trigger the device prompt, then:
test-scripts/rewire-okta-mcp.sh --verify
```

First create the MCP's own app in the console: **Create App Integration → OIDC → Native
Application**, grant type **Device Authorization**, then **Okta API Scopes → Grant** for
`okta.users.read`, `okta.groups.read`, `okta.apps.read`, `okta.apps.manage`, `okta.logs.read`.
Restart Claude Code afterwards and ask it to list applications — that triggers the device prompt.

Two silent failure modes the script exists to prevent, both of which make a rewired MCP still talk
to the old org:

- **The cached token is not keyed by org.** It is one global keyring entry
  (`OktaAuthManager`/`api_token`) validated on `exp` alone, never on `iss` — so an unexpired old-org
  token is reused against the new org and everything 403s. The script purges it first.
- **`OKTA_PRIVATE_KEY` + `OKTA_KEY_ID` force browserless auth** regardless of anything else, so
  overwriting only the org URL and client id leaves the old org's key material picking the mode. The
  script re-registers with no key material and asserts none survived.

> **Scope grants are per-app and silent.** The server drops tools whose scope is absent from the
> token — they never appear in `tools/list`. A missing tool is an ungranted scope in the console, not
> a broken install. Granting in the **Okta API Scopes** tab and listing in `OKTA_SCOPES` are two
> separate steps and both are required.
>
> **A successful device prompt is not evidence of grants.** `/oauth2/v1/device/authorize` accepts any
> scope string — measured: it accepted `okta.brands.manage` for an app never granted it. Grants are
> enforced only at token issuance, so the issued token's `scp` claim is the sole proof. That is what
> `--verify` reads; it names any scope you configured but never granted.
>
> **Register at user scope.** `claude mcp add` defaults to *project* scope, which binds the server to
> one directory and lets a stale user-scope entry keep serving every other worktree — two orgs
> depending on where you launched. The script forces `-s user` and fails if a project-scope
> `okta` entry shadows it.
>
> **The MCP cannot do O1/O3.** It has no `okta.authorizationServers.*` tools — that scope appears
> nowhere in its registry — so the authorization server and its **Audience** stay console-only. That
> is exactly the gap that stranded the old org, whose service app could read but never `*.manage`.

### O1. Decide the authorization server, once, before anything else

This choice writes the `iss` claim into every token and must be identical in the Okta app, SAP SOIDC,
and AgentCore. Changing it later means re-doing S2 on SAP. **Use the custom `default` server:**
`https://<org>.okta.com/oauth2/default`. The org server emits a bare `https://<org>.okta.com` and,
more importantly, has no server-level **Audience** field — which makes the audience gotcha below
unfixable. See "The one caveat that bites" for the full failure mode.

### O2. Create the app — Admin → Applications → Applications → Create App Integration

With `okta.apps.manage` granted (O0), the MCP's `create_application` does this in one call instead —
the settings below are the payload either way. Note Okta forces `pkce_required: true` on a web app
even with `client_secret_basic`, so the smoke test sends S256 PKCE by default; without it Okta 400s
at authorize with `PKCE code challenge is required by the application`.

- Sign-in method **OIDC — OpenID Connect**, application type **Web Application** (confidential —
  it must hold a client secret, because SAP's SOIDC audience check needs a client id that Okta will
  put in `aud`, and the local smoke test authenticates `client_secret_basic`).
- **Grant types:** `Authorization Code`. Add `Refresh Token` only if you intend to try
  `okta-userfed` later.
- **Sign-in redirect URIs:** `http://localhost:8086/callback` — this is the exact value
  `test-scripts/test-okta-sap-local.py` listens on. The local test needs nothing else. Deploying the
  frontend needs a *second* app, not another URI on this one — see the box below.
- **Assignments:** assign yourself (or a group containing you). An unassigned app fails at authorize
  with `access_denied`, which reads like a config error but is just an assignment.
- Record the **Client ID** and **Client secret**.

> **The smoke-test app cannot double as the SPA's app.** A Web Application is confidential — its
> `token_endpoint_auth_method` is `client_secret_basic`, so Okta demands a client secret at
> `/token`. `frontend/src` holds no client secret and must not (a secret shipped in a JS bundle is
> public), so it authenticates with PKCE alone and the exchange 400s `invalid_client` against a
> confidential app. Adding the frontend's URL to this app's redirect URIs does not fix that — the
> redirect succeeds and the code exchange is what fails.
>
> Create a **second** app for the SPA: application type **Single-Page Application** (`browser` over
> the API), grant type `Authorization Code`, PKCE (Okta forces it), no secret. Put *its* id in
> `frontend_overrides.client_id` and **add** it to `inbound_overrides.allowed_clients` — add, not
> replace; see [As `cdk/config.yaml`](#as-cdkconfigyaml) for why both ids belong in that list. If O3b's
> policy is scoped to *All clients* it inherits that grant and needs none of its own. Keeping the two
> apps separate also keeps the local smoke test working unchanged.
>
> `create_application` does this over the MCP too — application type `browser`, no secret. Record the
> SPA's own client id; it is not the O2 id.
>
> **Its redirect URI is the deployed app's origin, with no path.** `deploy-frontend.py:313` writes
> `redirect_uri = AmplifyUrl` verbatim — e.g. `https://main.<app-id>.amplifyapp.com` — so a
> `…/callback` suffix will not match, and the URL is Amplify's, not CloudFront's. Read the real value
> from the frontend stack's `AmplifyUrl` output after deploy and paste it exactly.

### O3. Set the audience — Admin → Security → API → `default` → Settings → Audience

Set **Audience = the Client ID from O2**. Okta ships `api://default`, and SAP rejects any token whose
`aud` omits SAP's own SOIDC client id — so leaving the default guarantees a SAP 401. This is
gotcha #2, and the fix is here on the IdP, never on SAP.

### O3b. Grant the app an access policy — same screen, **Access Policies** tab

The custom AS decides *per client* whether to mint a token at all, independently of the app config and
of whether the user signed in. A new app not covered by any rule fails **after** a successful login:

```
policy.evaluate_sign_on  → ALLOW          (user authenticated, MFA passed)
app.oauth2.as.authorize  → FAILURE        reason: no_matching_policy
```

The browser shows only `Policy evaluation failed for this request, please check the policy
configurations`, which reads like a broken app or a PKCE problem and is neither.

**Add Policy** → assign it to *The following clients* → the app (or All clients), then **Add Rule**
(defaults are fine) and confirm the rule grants `openid` + `email` and the **Authorization Code**
grant type. Rules evaluate top-down, so also check an existing higher-priority policy isn't scoped to
only the Okta-created apps. `grantedScopes: ""` in the System Log is the signature of this failure.

**Scope it to All clients unless you have a reason not to** — then a client added later, such as the
SPA from the box above, is covered the moment it is created and needs no second visit here.

**Two things that look like proof of this step are not.** A new app already carries an
`_links.accessPolicy` and logs two `policy.mapping.create` events at creation — but those are the app
**sign-on** policy (`ACCESS_POLICY`, e.g. "Any two factors") and `PROFILE_ENROLLMENT`, which govern
*whether the user may sign in*, not whether the AS mints a token. The authorization server's access
policies are a separate object with no app-level link, so neither signal says anything either way
about this step. Nor does a `200` from `/authorize`: that only validates client id, redirect URI and
PKCE, and renders the login page — policy evaluation happens *after* authentication, so a missing
rule surfaces as `access_denied` on the callback. What *is* evidence: the Access Policies tab, or —
since the MCP has no `okta.authorizationServers.*` tools — a System Log query for
`policy.lifecycle.create` / `policy.rule.add` filtered to `policyType = OAUTH_AUTHORIZATION_POLICY`,
whose `policyExtensiblePropertiesJson` names the client-include set. Neither the log nor the app
object exposes the rule's scope list; only the issued token's `scp` does (O4).

(Note the sign-on policy that ships by default will also demand MFA at login.)

### O4. Confirm what the org actually emits, before touching SAP

```bash
cp test-scripts/.env.example test-scripts/.env   # fill in OKTA_ISSUER / CLIENT_ID / CLIENT_SECRET
                                                #   and OKTA_EXPECT_AUDIENCE = the O2 client id
set -a; . test-scripts/.env; set +a
uv run test-scripts/test-okta-sap-local.py
```

The script preflights the discovery document and refuses to open a browser on an `iss` mismatch, then
asserts `aud` after the token exchange. Both gotchas fail here, locally, naming the fix — rather than
as a SAP 401 with nothing in `/IWFND/ERROR_LOG`. Expect it to reach SAP and 401 until S2 below is
done; the point of this step is the claims dump, which tells you exactly what to type into SOIDC.

### O5. SAP side — register the trust

Everything above is Okta-side. SAP has to be told to trust that issuer before any token it mints is
worth more than a 401.

**SOIDC trust is per SAP system.** STRUST, the SOIDC provider and the SU01 mapping user all live on
one system and none of them carry over to another, so a system with the same SID and client is still a
fresh build. Point the steps below at the system your `SAP_BASE_URL` actually resolves to.

Follow [`runbooks/uf-oidc.md`](runbooks/uf-oidc.md) S1–S4 (STRUST chain → SOIDC provider → claim
mapping → SICF) for the mechanism, substituting your org's issuer. The SAP-side trust is
topology-agnostic — one registration serves any Okta topology that forwards a user token. Two
settings are known-good:

- **SOIDC User Mapping Claim = `sub`, Mechanism = E-Mail.** Okta puts the email in `sub` and emits no
  `email` claim unless you add one. The O4 claims dump confirms this for your org.
- **ICF logon-procedure order** on the OData node — gotcha #1 above. Verify it before concluding the
  token is bad.

**But no deployable profile forwards an Okta user token today, so this trust has exactly one consumer:
the local smoke test.** `okta-userfed` would use it and is upstream-blocked in AgentCore Identity's 3LO
vault; `okta-basic` — the only deployable Okta profile — goes to SAP as a Basic technical user and never
touches SOIDC. Confirm the SAP side with the smoke test; a redeploy will not exercise it.

Keep the SOIDC mapping user distinct from the Basic outbound user for the same reason. If one SU01
account is both, an audit trail naming it cannot tell a forwarded user token from the technical user
acting. The mapping user must also be a **dialog** user: SOIDC's E-Mail mechanism resolves by email
address, and a technical user has none.

```bash
set -a; . test-scripts/.env; set +a
uv run test-scripts/test-okta-sap-local.py
```

Transaction **SOIDC** will validate a pasted `access_token` and show a green/red verdict; use
`--print-token` on the smoke test and paste it there to separate a trust problem from a mapping one.
A short dummy `Bearer probe` cannot do this job — it returns `malformed` whether or not the provider
exists, because junk fails structural parsing before SAP resolves the issuer.

## What you must supply

Both blocks are supplied via env vars (which win in CodeBuild) or `cdk/config.yaml`. Values are your
Okta org's — placeholders shown.

### Inbound (backend authorizer)

| Input | Env var | Example |
|---|---|---|
| Discovery URL | `AUTH_INBOUND_DISCOVERY_URL` | `https://<okta-domain>/oauth2/default/.well-known/openid-configuration` |
| Allowed clients | `AUTH_INBOUND_ALLOWED_CLIENTS` (CSV) | `spa-client-id,o3-audience` — see [below](#as-cdkconfigyaml) |

### Frontend (SPA OIDC)

| Input | Field | Example |
|---|---|---|
| Discovery URL | `discovery_url` | `https://<okta-domain>/oauth2/default/.well-known/openid-configuration` |
| SPA client id | `client_id` | `spa-client-id` |
| Authority | `authority` | `https://<okta-domain>/oauth2/default` |
| Scope (optional) | `scope` | `email openid profile offline_access` |

### As `cdk/config.yaml`

```yaml
auth_profile: okta-basic

frontend_overrides:
  discovery_url: https://<org>.okta.com/oauth2/default/.well-known/openid-configuration
  # oidc-client-ts throws at signin on a falsy authority even with metadata_url set.
  authority: https://<org>.okta.com/oauth2/default
  client_id: <SPA client id>
  scope: openid profile email

inbound_overrides:
  discovery_url: https://<org>.okta.com/oauth2/default/.well-known/openid-configuration
  allowed_clients:
    - <SPA client id>       # id_token `aud` at the API Gateway authorizer
    - <O3 audience>         # access_token `aud` at the AgentCore runtime
```

**`allowed_clients` is one list read by two authorizers against two different tokens**, so when the
SPA's client id and the O3 Audience differ it needs both entries. `emit_resolved_profile.py:60`
applies the single list to both legs:

| Leg | Token it sees | What it matches | Value |
|---|---|---|---|
| API Gateway — `lambdas/jwt_authorizer/index.py:50` | `id_token` | `aud` / `cid` / `azp` / `client_id` | the **requesting client** — the SPA's id |
| AgentCore runtime — `backend-stack.ts:744` | `access_token` | `allowedAudience` → `aud` | the **AS-level O3 Audience** |

The naming is Cognito-era: `backend-stack.ts` routes external issuers to `allowedAudience` rather than
`allowedClients`, because Okta access tokens carry no `client_id` claim at all. Setting O3's Audience
equal to the *confidential* app's client id is a SAP requirement (gotcha #2), which is why it stays
pinned there and the SPA's id is added alongside rather than swapped in.

### The external MCP stack: only its `AuthFlow` has to say BASIC

`sap_mcp.external_stack` needs a vendor stack running `AuthFlow=BASIC`. Its **`InboundAuthProvider` is
a separate parameter and does not have to be Okta** — those two axes are independent, and CDK synth
enforces only the flow. So the Gateway may keep presenting a Cognito or Entra token to the runtime
while the *user* logs in through Okta; the user's token is validated at our own authorizer, not the
vendor runtime's. Whatever IdP that inbound parameter names, `external_stack` must carry the matching
client id / discovery URL / client-secret ARN, because the Gateway's credential provider is what mints
that token.

Pointing the profile at an `AuthFlow=ON_BEHALF_OF_TOKEN_EXCHANGE` stack fails at synth with a named
error — `basic` outbound cannot ride an OBO runtime, whose authorizer expects a user JWT.

## The one caveat that bites: authorization-server URL shape

Okta has **two** discovery-URL shapes and you must supply the right one for your org:

- **Org authorization server:** `https://<okta-domain>/.well-known/openid-configuration`
- **Custom authorization server:** `https://<okta-domain>/oauth2/<authserver-id>/.well-known/openid-configuration`
  (the `default` server is `.../oauth2/default/...`)

The authorizer and frontend pass `discovery_url` through **verbatim** (as `metadata_url`), so a
custom-auth-server URL round-trips unchanged — but a wrong one silently fails at sign-in. This is a
config choice, not something the code can guess.

> **Failure mode (per Okta's authorization-server docs).** The two servers emit
> **different `iss` claims**, and SAP + AgentCore both validate `iss`:
> - Org server `/oauth2/v1/` → `iss = https://<okta-domain>` — does **NOT** match SAP/AgentCore config.
> - Custom (default) server `/oauth2/default/v1/` → `iss = https://<okta-domain>/oauth2/default` — matches.
>
> Use the **`/oauth2/default`** endpoints consistently across the Okta app (authorize/token URLs),
> the SAP SOIDC issuer, and AgentCore's `discoveryUrl`, so all three agree. A mismatch surfaces as a
> **401 from AgentCore** (issuer ≠ configured discovery URL) or a **401 from SAP** (issuer ≠ SOIDC
> config). Decode the `access_token` and check `iss` to confirm. Also use the **access_token**, not
> the `id_token`, for the SAP call.

## Identity join key — email in `sub` (simpler than Entra)

Okta puts the user's email in the `sub` claim, so the email join key used for IAS / user-federation
mapping works out of the box. This is *simpler* than Entra, whose `sub` is an opaque app-pairwise id
requiring a Feature-Pack-2+ custom claim mapping to surface email/UPN. No code difference — the agent's
`get_inbound_identity` reads `email` / `sub` / `iss` generically — just less SAP-side setup for Okta.

## Out of scope

`obo-okta` (Okta on-behalf-of token exchange) is a **separate, experimental** outbound value — AWS
documents OBO out-of-the-box only for Entra (`MicrosoftOauth2`); Okta OBO needs a hand-rolled
`CustomOauth2` provider. It is not part of either Okta profile here.
