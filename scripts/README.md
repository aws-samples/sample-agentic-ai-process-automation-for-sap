<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Scripts

These scripts hold the logic. Two dispatchers call them, and neither one duplicates them:

- **`python3 launch.py`** — deploy and operate the sample. Needs only Python, so it works on a clean clone.
- **`make`** — contributor tooling: lint, tests, type generation, packaging. Run `make` to see every target.

Make's deploy and operate targets delegate to the launcher, so `make deploy-all` and `python3 launch.py deploy` are the same thing.

## Getting Started

```bash
python3 launch.py doctor    # check prerequisites and AWS access; changes nothing
python3 launch.py           # guided launch
```

After deployment, sync SAP credentials and knowledge base content:

```bash
python3 launch.py sync-sap
python3 launch.py sync-kb
```

## Directory Layout

```
scripts/
├── setup.py                  # Superseded by `python3 launch.py` — kept until the launcher is validated in CI
├── sync-sap-secret.sh        # Superseded by `python3 launch.py sync-sap`
├── sync-channel-secret.sh    # Superseded by `python3 launch.py sync-channel`
├── sync-knowledge-base.sh    # Superseded by `python3 launch.py sync-kb`
├── utils.py                  # Shared Python utilities (used by test-scripts/)
├── requirements.txt          # Python deps for the legacy setup wizard
│
├── deploy/                   # Deployment scripts
│   ├── deploy-frontend.py    # Build + deploy frontend to Amplify (the launcher wraps this)
│   ├── run_emit.py           # Resolve auth_profile → .auth-profile-resolved.json (cdk/bin/app.ts calls this)
│   └── deploy-with-codebuild.py  # Full stack deploy via ephemeral CodeBuild project
│
├── dev/                      # Contributor tooling — called by make
│   ├── lint.sh               # All linters and formatters (--fix | --check)
│   ├── generate-types.sh     # Generate TS + Python types from JSON Schema (--list prints the outputs)
│   ├── check-types.sh        # Fail if the committed generated types are stale (CI)
│   ├── pre-commit-checks.sh  # Regenerate types, auto-fix lint, stage the result
│   ├── pre-commit.sh         # The git hook itself (install via `make install-hooks`)
│   ├── install-hooks.sh      # Install the hook, resolving the hooks dir via git (worktree-safe)
│   ├── bump-version.sh       # Bump VERSION and the package manifests
│   ├── package-release.sh    # Build a clean zip for external sharing
│   ├── local-dev.sh          # Start agent container + frontend dev server (`config` writes aws-exports.json only)
│   └── setup-container-runtime.sh  # Detect Docker/Finch (only for deployment_type: docker)
│
├── ops/                      # Operational scripts
│   ├── autonomy.sh           # Superseded by `python3 launch.py autonomy`
│   └── setup-ses-domain.sh   # SES domain identity setup (DKIM, MX, config.yaml)
│
└── data/                     # Sample data and evaluation setup
    └── setup_evaluations.py  # Configure online evaluation settings
```

Scripts marked **superseded** still work when run directly, but nothing documented calls them any more. They are kept until the launcher has been validated against a real deployment in CI, then they go. Prefer the launcher command.

## Common Tasks

| Task | Command | Make alias |
|------|---------|------------|
| First-time setup | `python3 launch.py` | `make setup` |
| Check prerequisites | `python3 launch.py doctor` | — |
| Full redeploy | `python3 launch.py deploy` | `make deploy-all` |
| Deploy CDK only | `python3 launch.py infra` | `make deploy` |
| Deploy frontend only | `python3 launch.py frontend` | `make deploy-frontend` |
| Refresh Lambdas | `python3 launch.py refresh` | `make refresh-lambdas` |
| Deployment status | `python3 launch.py status` | `make status` |
| Resume after interruption | `python3 launch.py resume` | — |
| Review pending changes | `python3 launch.py diff` | — |
| Validate without deploying | `python3 launch.py synth` | `make cdk-synth` |
| Sync SAP credentials | `python3 launch.py sync-sap` | `make sync-sap-secret` |
| Sync channel webhook secret | `python3 launch.py sync-channel` | `make sync-channel-secret` |
| Sync knowledge base | `python3 launch.py sync-kb` | `make sync-kb` |
| Check/set autonomy | `python3 launch.py autonomy` | `make autonomy` |
| Local frontend dev | — | `make local-config` |
| Local agent + frontend | — | `make local-dev` |
| Lint and format | — | `make lint` |
| Run tests | — | `make test` |
| Deploy via CodeBuild | `python3 scripts/deploy/deploy-with-codebuild.py` | — |
| Set up SES domain | `./scripts/ops/setup-ses-domain.sh <domain>` | — |
