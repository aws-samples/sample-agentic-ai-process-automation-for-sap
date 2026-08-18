# Makefile — contributor entry points for the ERP Agent platform
#
# This file is a dispatcher, not an implementation. Every target delegates:
#
#   deploy and operate  ->  python3 launch.py <command>
#   developer tooling   ->  scripts/dev/*.sh, scripts/deploy/*.py
#
# Nothing here holds logic of its own, so a target and the thing it runs cannot
# drift apart. Recipes that once lived inline — the guided setup prompts and the
# Lambda refresh — moved into the launcher, where they are testable and where
# failures are actionable.
#
# Deploying the sample? Use `python3 launch.py` directly. Make is for
# contributors, and needs GNU make; the launcher needs nothing but Python.
#
# Pass launcher flags through LAUNCH_ARGS, which lands before the subcommand:
#   make deploy-all LAUNCH_ARGS=--yes
#   make status LAUNCH_ARGS="--profile dev --region us-west-2"

LAUNCH := python3 launch.py $(LAUNCH_ARGS)

GREEN := \033[0;32m
NC    := \033[0m

# Help categories, in display order. Underscores render as spaces.
CATEGORIES := Deploy Operate Developer_tools Code_quality

.PHONY: help launch setup deploy deploy-frontend deploy-all \
        refresh-lambdas sync-sap-secret sync-channel-secret sync-kb autonomy status \
        local-dev local-config install-hooks pre-commit validate cdk-synth \
        emit-profile test bump-version generate-types check-types package \
        lint ruff-lint format eslint prettier lint-cicd

# ── Help (default) ────────────────────────────────────────────────────────────
# Built from the `##@Category Description` tags below, so a new target appears
# here automatically. The previous version grepped hard-coded target-name lists,
# which meant adding a target silently made it invisible.

help:
	@echo ""
	@echo "  Usage: make <target>          (or: python3 launch.py --help)"
	@awk -v categories="$(CATEGORIES)" -F':.*##@' ' \
	    /^[a-zA-Z0-9_-]+:.*##@/ { \
	      space = index($$2, " "); \
	      category = substr($$2, 1, space - 1); \
	      body[category] = body[category] sprintf("    \033[0;36m%-20s\033[0m %s\n", $$1, substr($$2, space + 1)); \
	    } \
	    END { \
	      count = split(categories, ordered, " "); \
	      for (i = 1; i <= count; i++) { \
	        name = ordered[i]; \
	        if (body[name] == "") continue; \
	        title = name; gsub(/_/, " ", title); \
	        printf "\n  %s\n%s", title, body[name]; \
	      } \
	      printf "\n"; \
	    }' $(MAKEFILE_LIST)

# ── Deploy ────────────────────────────────────────────────────────────────────

launch: ##@Deploy Guided launcher — clean clone to a running sample
	@$(LAUNCH)

setup: ##@Deploy Alias for `launch` (the guided first-time flow)
	@$(LAUNCH)

deploy: ##@Deploy Deploy the CDK stacks only
	@$(LAUNCH) infra

deploy-frontend: ##@Deploy Build and deploy the frontend only
	@$(LAUNCH) frontend

deploy-all: ##@Deploy Full redeploy — stacks, Lambda refresh, frontend (confirms the target)
	@$(LAUNCH) deploy

# ── Operate ───────────────────────────────────────────────────────────────────

status: ##@Operate Report deployed stacks, endpoints, and failures
	@$(LAUNCH) status

refresh-lambdas: ##@Operate Force this stack's Lambdas to cold-start
	@$(LAUNCH) refresh

sync-sap-secret: ##@Operate Sync SAP credentials to Secrets Manager
	@$(LAUNCH) sync-sap

sync-channel-secret: ##@Operate Store the notification webhook signing secret
	@$(LAUNCH) sync-channel

sync-kb: ##@Operate Publish SOPs + API docs to S3 and start ingestion
	@$(LAUNCH) sync-kb

autonomy: ##@Operate Read or set the trigger mode (make autonomy CMD="set auto")
	@$(LAUNCH) autonomy $(or $(CMD),get)

# ── Developer tools ───────────────────────────────────────────────────────────

local-dev: ##@Developer_tools Start the agent container plus the frontend dev server
	@./scripts/dev/local-dev.sh

local-config: ##@Developer_tools Generate aws-exports.json for local frontend dev
	@./scripts/dev/local-dev.sh config

install-hooks: ##@Developer_tools Install the git pre-commit hook
	@./scripts/dev/install-hooks.sh

pre-commit: ##@Developer_tools Regenerate types, auto-fix lint, stage the result
	@./scripts/dev/pre-commit-checks.sh

validate: pre-commit cdk-synth ##@Developer_tools Full check — run before pushing or raising a CR
	@echo "$(GREEN)Full validation passed — safe to push.$(NC)"

cdk-synth: ##@Developer_tools Validate the CDK app without deploying
	@$(LAUNCH) synth

emit-profile: ##@Developer_tools Preview .auth-profile-resolved.json for the selected auth_profile
	@python3 scripts/deploy/run_emit.py --backend cdk

test: ##@Developer_tools Run the pytest suite
	@python3 -m pytest tests/

generate-types: ##@Developer_tools Generate TS + Python types from JSON Schema
	@./scripts/dev/generate-types.sh

check-types: ##@Developer_tools Verify the committed generated types are current (CI)
	@./scripts/dev/check-types.sh

bump-version: ##@Developer_tools Bump the version (usage: make bump-version VERSION=0.7.0)
	@./scripts/dev/bump-version.sh $(VERSION)

package: ##@Developer_tools Package a clean zip for external sharing
	@./scripts/dev/package-release.sh

# ── Code quality ──────────────────────────────────────────────────────────────

lint: ##@Code_quality Auto-fix every linting and formatting issue
	@./scripts/dev/lint.sh --fix

lint-cicd: ##@Code_quality Check-only lint for CI — no auto-fix
	@./scripts/dev/lint.sh --check

ruff-lint: ##@Code_quality Ruff lint with auto-fix
	@ruff check --fix

format: ##@Code_quality Format Python with ruff
	@ruff format

eslint: ##@Code_quality ESLint on the frontend with auto-fix
	@cd frontend && npx eslint --fix src/

prettier: ##@Code_quality Prettier on the frontend
	@cd frontend && npx prettier --write "src/**/*.{ts,tsx,js,jsx,css,json}"
