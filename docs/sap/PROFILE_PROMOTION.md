<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Promoting an Auth Profile

An auth profile advertises a topology. Two independent, orthogonal facts decide how
loudly the sample may advertise it — do not conflate them.

| Signal | Where | Means | How you clear it |
|--------|-------|-------|------------------|
| `status: stub` (per **axis**) | `auth-profiles.yaml` → `axes.*` | The IaC module for that axis value is **not built** | Build the module; `make cdk-synth` passes; a dry-run `cdk deploy` stands the stack up |
| `verified: true` (per **profile**) | `auth-profiles.yaml` → `profiles.*` | This exact profile was run **end-to-end against a live SAP system** | Run it against real SAP; capture the system + SAP_BASIS version |

`maturity` (`ga`/`preview`/`experimental`) is a third, separate signal — the *weakest*
axis's hardening level, computed automatically. It is not a promotion gate; it's a caveat.

## The two blocks

- **`profiles:`** — deployable today. Every selected axis value has a built IaC module
  (**zero stub axes**). A [contract test](../../tests/unit/test_auth_profiles.py)
  (`test_deployable_profiles_have_no_stub_axes`) fails CI if a stub-axis profile lands here.
- **`preview_profiles:`** — roadmap. At least one selected axis is `status: stub`. They
  resolve + validate (the topology is *legal*) but cannot deploy. `test_preview_profiles_each_have_a_stub_axis`
  fails CI if a fully-built profile is left here (it should be promoted).

So the split is enforced, not aspirational: you **cannot** move a profile into `profiles:`
while any of its axes is still `status: stub`. That is the whole point — "it's an accepted
industry pattern" is not a reason to promote. Built-and-synthesizable is.

## Two-step promotion

Promotion is a ladder, not a jump. A profile earns `profiles:` membership before it earns
a `verified` badge.

### Step 1 — reach `profiles:` (deployable)

Do this when the IaC exists and stands up. **Does NOT require live SAP.**

1. Build the IaC module(s) for every `status: stub` axis the profile selects.
2. Clear `status: stub` on those axis values in `auth-profiles.yaml → axes`.
   (Axis status is shared: clearing `inbound/jwt-authorizer`'s stub may affect both
   `entra` and `okta` — clear only the value you actually built. See
   `test_entra_inbound_proven_okta_still_stub` for why they diverge.)
3. Move the profile from `preview_profiles:` to `profiles:`, leaving `verified` **unset/false**.
4. `make validate` (runs the contract tests + `cdk synth`). Green = deployable.
5. Do a real `cdk deploy` into a scratch account to confirm it stands up.
6. Docs: add the row to [`AUTH_PROFILE_SELECTION.md`](./AUTH_PROFILE_SELECTION.md) "Deploys today"
   with the Verified column left as `—` (deploys; not yet run against live SAP).

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

## Anti-patterns

- ❌ Promoting on "it's a standard pattern" without building/synthing the IaC. The stub-axis
  test blocks this; don't try to route around it by hand-clearing a stub you didn't build.
- ❌ Setting `verified: true` off a mock or a colleague's separate POC. Verified means *this*
  profile, *this* repo's wiring, *a live* SAP.
- ❌ Clearing a shared axis stub for a value you didn't prove (clearing `okta` because you
  proved `entra` — they share the `jwt-authorizer` module but not the proof).

## See also

- [`auth-profiles.yaml`](../../auth-profiles.yaml) — the catalog (source of truth)
- [`AUTH_PROFILE_SELECTION.md`](./AUTH_PROFILE_SELECTION.md) — which profile to pick
- [`tests/unit/test_auth_profiles.py`](../../tests/unit/test_auth_profiles.py) — the enforced contracts
