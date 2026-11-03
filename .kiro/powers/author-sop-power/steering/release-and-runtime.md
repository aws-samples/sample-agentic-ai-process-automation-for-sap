<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Release, Runtime and Research

Read when the user names another SAP release or runtime, when a document implies another release, or before researching.

## Another release

When a document describes another release's behaviour (for example separate vendor master maintenance), ask in Round 1: "Your document describes <behaviour>, which is ECC-style. Are you on ECC, or was this written before your S/4HANA move?"; the default stands until answered.

On ECC, PURPOSE names the release, release-dependent steps follow ECC behaviour (researched when unsure), business objects carry that release's names, no S/4HANA-only concept or app appears (Business Partner for suppliers), and the hand-off and any drafted `base_prompt.txt` name the release.

## Another runtime

Ask one plain question: "How does the agent set a case status, wait for a person and pick up the answer, and how are configurable values and contacts written?" Adapt only the clauses the answer changes; the rest of the template stays. Never investigate runtime code. Without an answer, or when the user wants the procedure to stand alone, the default way to adapt is `plain-procedure.md`.

## Research

Research only a release-dependent rule (Business Partner vs vendor master), a country or regulatory rule, a named industry practice, or a release correction, and on the default release only when unsure. Use help.sap.com, SAP Learning and SAP Notes or KBAs first, and SAP Community only with a second source. Add one "Checked:" line per finding to the Fit Summary and the hand-off. If research is inconclusive or no web tool is available, ask the user.
