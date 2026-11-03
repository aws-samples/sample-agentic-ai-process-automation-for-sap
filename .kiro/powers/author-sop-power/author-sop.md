<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SOP Authoring: moved to the SAP Agent SOP Writer power

SOP authoring in this repo now uses the SAP Agent SOP Writer power in this folder (`POWER.md` and `steering/`).

To use it in Kiro: Kiro Powers -> Add Custom Power -> Local Directory -> select this folder (`.kiro/powers/author-sop-power/`), then follow its `POWER.md`.

If you are an agent reading this file via `@author-sop`: read `POWER.md` in this folder and follow it, and the steering files it names, for the current request.

Hand-offs from the `author-skill` and `add-use-case` powers still apply. The declared `{{SYMBOL}}` constants, domain context, SAP entities and business rules they pass along are inputs to this power's intake.
