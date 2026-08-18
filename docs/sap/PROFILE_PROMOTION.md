<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Promoting an Auth Profile

An auth profile advertises a topology. Two independent, orthogonal facts decide how
loudly the sample may advertise it — do not conflate them.

| Signal | Where | Means | How you clear it |
|--------|-------|-------|------------------|
| `status: stub` (per **axis**) | `auth-profiles.yaml` → `axes.*` | This repository's CDK deployment path cannot stand that axis value up end to end. Why is a separate fact — see [`blocked_by`](#blocked_by--why-an-axis-is-stub) below | Clear whatever `blocked_by` names; `make cdk-synth` passes; a scratch `cdk deploy` stands up the repository-owned resources when external prerequisites are supplied |
| `verified: true` (per **profile**) | `auth-profiles.yaml` → `profiles.*` | This exact profile was run **end-to-end against a live SAP system** | Run it against real SAP; capture the system + SAP_BASIS version |

`maturity` (`ga`/`preview`/`experimental`) is a third, separate signal — the *weakest*
axis's hardening level, computed automatically. It is not a promotion gate; it's a caveat.

### `blocked_by` — why an axis is stub

`status: stub` says an axis isn't deployable end to end; it does **not** say the wiring is
missing. Those are different facts with different owners, and collapsing them makes every
stub read as "nobody built it." So each stub axis declares `blocked_by`:

| `blocked_by` | Means | Who clears it |
|---|---|---|
| `repo` | The IaC/runtime/adapter wiring genuinely does not exist here | Us, by writing code |
| `operator` | Wiring exists and is exercised; awaiting external config (an IdP tenant, a trust) | Whoever owns that external system |
| `upstream` | Wiring exists; blocked by a defect in an AWS service | AWS |

Absent `blocked_by` defaults to `repo` — the strict reading, so an unannotated stub is never
flattered. `stub_blockers()` surfaces this per axis and the emitted artifact's banner names
the cause, because "no IaC yet" was actively wrong for `operator`/`upstream` axes.

**`blocked_by` is not a promotion gate.** It never substitutes for clearing `status: stub`,
and an `operator`-blocked axis is exactly as undeployable as a `repo`-blocked one. It changes
what the banner *says*, not what the profile is allowed to claim. Only the two signals above
gate promotion.

## The two blocks

- **`profiles:`** — supported by this repository's CDK deployment path. Every selected
  axis has the required repository-owned IaC/runtime/adapter wiring (**zero stub axes**).
  Operator-owned external prerequisites may still be required. A
  [contract test](../../tests/unit/test_auth_profiles.py)
  (`test_deployable_profiles_have_no_stub_axes`) fails CI if a stub-axis profile lands here.
- **`preview_profiles:`** — roadmap. At least one selected axis is `status: stub`. The
  topology resolves and validates as legal, but the repository's CDK deployment path does
  not yet support it. `test_preview_profiles_each_have_a_stub_axis` fails CI if a fully
  supported profile is left here (it should be promoted).

So the split is enforced, not aspirational: you **cannot** move a profile into `profiles:`
while any of its axes is still `status: stub`. That is the whole point — "it's an accepted
industry pattern" is not a reason to promote. The repository wiring must be implemented,
synthesized, and deployment-tested.

## Two-step promotion

Promotion is a ladder, not a jump. A profile earns `profiles:` membership before it earns
a `verified` badge.

### Step 1 — reach `profiles:` (supported by the CDK deployment path)

Do this when this repository's required wiring exists and its resources stand up with the
documented external prerequisites supplied. **This does not require a successful live-SAP call.**

1. Implement the required IaC/runtime/adapter wiring in this repository for every `status: stub` axis the profile selects.
2. Clear `status: stub` on those axis values in `auth-profiles.yaml → axes`.
   (Axis status is shared: clearing `inbound/jwt-authorizer`'s stub may affect both
   `entra` and `okta` — clear only the value you actually built, on its own evidence. See
   `test_entra_and_okta_inbound_both_proven_independently`, and
   `test_okta_userfed_still_stub_via_outbound` for a profile that shares both cleared Okta
   axes and stayed in preview anyway on its own blocked outbound.)
3. Move the profile from `preview_profiles:` to `profiles:`, leaving `verified` **unset/false**.
4. `make validate` (runs the contract tests + `cdk synth`). Green confirms the
   repository's static deployment contract; it does not establish live-SAP verification.
5. Do a real `cdk deploy` in a scratch account, supplying documented external prerequisites,
   to confirm the repository-owned resources stand up.
6. Docs: add the row to [`AUTH_PROFILE_SELECTION.md`](./AUTH_PROFILE_SELECTION.md)
   "Supported by this repository's CDK deployment path" with the Verified column left as `—`
   (CDK path supported; not yet run against live SAP).

### Step 2 — set `verified: true`

Do this only after a live end-to-end run against a real SAP system.

1. Run the full flow (login → agent → SAP OData read/write) against live SAP.
2. Set `verified: true` on the profile and note the system in the trailing comment
   (e.g. `# verified E2E (S/4HANA 2023, SAP_BASIS 7.58)`).
3. Point the profile at its operator runbook under [`runbooks/`](./runbooks/).
4. Add the `✅ <system>` marker to the Verified column in the selection guide.

**The `verified` bar is strict: a live SAP system, not a mock.** A `verified` flag that
accepts the mock MCP responses is not worth having — it would claim proof the sample
doesn't have.

## Worked example — `entra-obo`

- **Was:** `preview_profiles`, all three of frontend/inbound/outbound `status: stub`.
- **Step 1:** the `frontend/direct-idp`, `inbound/jwt-authorizer`, and `outbound/obo` modules
  were built; the OBO-vs-Gateway guard was fixed (`validate_profile` exempts `obo_direct_mcp`);
  stubs cleared for the `entra` values only (okta stayed stub).
- **Step 2:** run E2E against S/4HANA 2023 (SAP_BASIS 7.58) on 2026-07-08 → `verified: true`.
- **Now:** `profiles:`, zero stub axes, `verified: true`. Not zero-config — needs Entra
  `frontend_overrides` + `inbound_overrides`.

## Worked example — `okta-basic`, promoted to Step 1 only

The useful contrast: a profile that earned `profiles:` membership and will likely never earn
`verified`.

- **Was:** `preview_profiles`, `frontend: direct-okta` and `inbound: okta` both
  `status: stub, blocked_by: operator` — the modules were built and proven on Entra, but no Okta
  org existed to point them at.
- **Step 1 (2026-07-31):** an Okta org was supplied and the profile deployed. A real login through
  the deployed SPA (PKCE, public client, no secret) issued an `id_token` that the deployed
  authorizer accepted, and the request reached the backend Lambda — Okta's log and CloudWatch agree
  on the same second. Both stubs cleared, profile moved to `profiles:`.
- **Step 2: not attempted, and not pending.** This profile's outbound is `basic` — a shared
  technical user. No per-user identity reaches SAP through it, so a live-SAP run would verify the
  Basic flow, not anything Okta. `verified` stays unset.

Two things this example is here to show. First, `blocked_by: operator` was an honest label: supplying
the external config *was* the entire remaining task. Second, clearing a shared axis does not cascade —
`okta-userfed` selects both of the same Okta axes and stayed in `preview_profiles`, because its
`user-federation` outbound is independently `upstream`-blocked.

## Anti-patterns

- ❌ Promoting on "it's a standard pattern" without building/synthing the IaC. The stub-axis
  test blocks this; don't try to route around it by hand-clearing a stub you didn't build.
- ❌ Setting `verified: true` off a mock or a colleague's separate POC. Verified means *this*
  profile, *this* repo's wiring, *a live* SAP.
- ❌ Clearing a shared axis stub for a value you didn't prove (clearing `okta` because you
  proved `entra` — they share the `jwt-authorizer` module but not the proof). Both are cleared
  now, but each on its own login against its own IdP.
- ❌ Clearing an axis on evidence that stops short of the claim. A rendered IdP login page proves
  the redirect, not authentication; an authorizer denying an unsigned token proves it fetched the
  JWKS, not that it accepts a real one. Both are worth recording, neither clears a stub.
- ❌ Reading `blocked_by: operator` as "nearly promoted". It means the remaining work is
  someone else's, not that it's done — the axis is still `status: stub` and the profile still
  cannot deploy. Supply the external config, run it, *then* clear the stub. (The Okta axes are the
  worked example: `operator` for weeks, cleared in an afternoon once an org existed. The label was
  accurate the whole time and still didn't make the profile deployable.)

## See also

- [`auth-profiles.yaml`](../../auth-profiles.yaml) — the catalog (source of truth)
- [`AUTH_PROFILE_SELECTION.md`](./AUTH_PROFILE_SELECTION.md) — which profile to pick
- [`tests/unit/test_auth_profiles.py`](../../tests/unit/test_auth_profiles.py) — the enforced contracts
