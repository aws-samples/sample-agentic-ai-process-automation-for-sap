# Makefile — developer workflows for the ERP Agent platform
#
# Quick reference:
#   make              — show this help
#   make setup        — guided first-time setup (bootstrap → SAP creds → KB sync)
#   make deploy-all   — full redeploy (CDK + refresh Lambdas + frontend)
#   make lint         — auto-fix all linting issues

# ── Config ────────────────────────────────────────────────────────────────────

RED    := \033[0;31m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
CYAN   := \033[0;36m
NC     := \033[0m

# Generated type files (single source of truth — must match scripts/dev/generate-types.sh).
# Python models live in the shared_types Lambda layer, not at the repo root.
GENERATED_TYPES := frontend/src/types/generated-cases.ts \
                   lambdas/layers/shared_types/generated_cases.py \
                   frontend/src/types/generated-tickets.ts \
                   lambdas/layers/shared_types/generated_tickets.py

.PHONY: help setup deploy deploy-frontend deploy-all refresh-lambdas \
        sync-sap-secret sync-channel-secret sync-kb autonomy local-dev local-config \
        install-hooks pre-commit validate cdk-synth emit-profile test bump-version \
        generate-types check-types lint ruff-lint format eslint prettier lint-cicd \
        package

# ── Help (default) ────────────────────────────────────────────────────────────

help: ## Show this help
	@echo ""
	@echo "  Usage: make <target>"
	@echo ""
	@echo "  Getting Started"
	@grep -E '^(setup|deploy-all|deploy|deploy-frontend) *:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "    \033[0;36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Operations"
	@grep -E '^(refresh-lambdas|sync-sap-secret|sync-channel-secret|sync-kb|autonomy) *:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "    \033[0;36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Development"
	@grep -E '^(local-dev|local-config|install-hooks|pre-commit|validate|cdk-synth|emit-profile|generate-types|check-types|bump-version|test|package) *:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "    \033[0;36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Code Quality"
	@grep -E '^(lint|ruff-lint|format|eslint|prettier|lint-cicd) *:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "    \033[0;36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ── Getting Started ───────────────────────────────────────────────────────────

setup: ## Guided first-time setup (bootstrap → SAP creds → KB sync)
	@echo ""
	@echo "$(CYAN)═══ ERP Agent — First-Time Setup ═══$(NC)"
	@echo ""
	@echo "This will walk you through:"
	@echo "  1. Bootstrap (prereqs, config, CDK deploy, frontend)"
	@echo "  2. Sync SAP credentials to Secrets Manager"
	@echo "  3. Sync knowledge base (SOPs + API docs) to S3"
	@echo ""
	@read -p "Ready to start? [Y/n] " yn; \
	case "$$yn" in [nN]*) echo "Aborted."; exit 0;; esac
	@echo ""
	@echo "$(CYAN)── Step 1/3: Bootstrap ──$(NC)"
	@python -m pip install -q -r scripts/requirements.txt
	@python scripts/setup.py
	@echo ""
	@echo "$(CYAN)── Step 2/3: SAP Credentials ──$(NC)"
	@echo "Sync your SAP credentials (base URL, username, password) to Secrets Manager."
	@read -p "Sync SAP credentials now? [Y/n] " yn; \
	case "$$yn" in [nN]*) echo "Skipped. Run 'make sync-sap-secret' later.";; *) ./scripts/sync-sap-secret.sh;; esac
	@echo ""
	@echo "$(CYAN)── Step 3/3: Knowledge Base ──$(NC)"
	@echo "Upload SOPs and SAP API docs to S3 and trigger Bedrock KB re-ingestion."
	@read -p "Sync knowledge base now? [Y/n] " yn; \
	case "$$yn" in [nN]*) echo "Skipped. Run 'make sync-kb' later.";; *) ./scripts/sync-knowledge-base.sh;; esac
	@echo ""
	@echo "$(GREEN)═══ Setup complete! ═══$(NC)"
	@echo ""
	@echo "  Next steps:"
	@echo "    make deploy-all     — full redeploy after code changes"
	@echo "    make autonomy       — check/set autonomy controls"
	@echo "    make help           — see all available targets"
	@echo ""

deploy: ## Deploy CDK stacks
	cd cdk && cdk deploy --all --progress events

deploy-frontend: ## Deploy frontend to Amplify
	python scripts/deploy/deploy-frontend.py

deploy-all: deploy refresh-lambdas deploy-frontend ## Full redeploy (CDK + refresh Lambdas + frontend)
	@echo "$(GREEN)Full deploy complete.$(NC)"

# ── Operations ────────────────────────────────────────────────────────────────

refresh-lambdas: ## Force all Lambdas to cold-start (pick up new SSM values)
	@STACK=$$(grep '^stack_name_base:' cdk/config.yaml | awk '{print $$2}'); \
	REGION=$$(aws configure get region 2>/dev/null || echo us-east-1); \
	echo "Refreshing Lambdas for stack '$$STACK' in $$REGION..."; \
	FUNCS=$$(aws lambda list-functions --region $$REGION \
		--query "Functions[?starts_with(FunctionName, '$$STACK')].FunctionName" \
		--output text); \
	STAMP=$$(date +%s); \
	for fn in $$FUNCS; do \
		EXISTING=$$(aws lambda get-function-configuration --function-name $$fn --region $$REGION \
			--query 'Environment.Variables' --output json 2>/dev/null || echo '{}'); \
		UPDATED=$$(echo "$$EXISTING" | python3 -c "import sys,json; d=json.load(sys.stdin) or {}; d['CACHE_BUST']=str($$STAMP); print(json.dumps({'Variables':d}))"); \
		aws lambda update-function-configuration --function-name $$fn --region $$REGION \
			--environment "$$UPDATED" --output text --query 'FunctionName' 2>/dev/null \
			&& echo "  $(GREEN)✓$(NC) $$fn" \
			|| echo "  $(RED)✗$(NC) $$fn (skipped)"; \
	done; \
	echo "$(GREEN)Done — all Lambdas will cold-start on next invocation.$(NC)"

sync-sap-secret: ## Sync SAP credentials to Secrets Manager
	./scripts/sync-sap-secret.sh

sync-channel-secret: ## Sync webhook signing secret into channel Secrets Manager secret
	./scripts/sync-channel-secret.sh

sync-kb: ## Sync knowledge base (SOPs + API docs) to S3
	./scripts/sync-knowledge-base.sh

autonomy: ## Show current autonomy controls (use: make autonomy CMD="set trigger-mode auto")
	./scripts/ops/autonomy.sh $(or $(CMD),get)

# ── Development ───────────────────────────────────────────────────────────────

local-dev: ## Start agent container + frontend dev server
	./scripts/dev/local-dev.sh

local-config: ## Generate aws-exports.json for local frontend dev
	./scripts/dev/local-dev.sh config

install-hooks: ## Install git pre-commit hook
	@cp scripts/dev/pre-commit.sh .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "$(GREEN)Pre-commit hook installed.$(NC)"

pre-commit: generate-types lint ## Run pre-commit checks
	@if ! git diff --quiet $(GENERATED_TYPES); then \
		git add $(GENERATED_TYPES); \
		echo "$(YELLOW)Auto-staged regenerated types.$(NC)"; \
	fi

validate: pre-commit cdk-synth ## Full validation — run before pushing or raising a CR
	@echo "$(GREEN)Full validation passed — safe to push.$(NC)"

cdk-synth: ## CDK synth check (no bundling)
	@echo "Running CDK synth..."
	@cd cdk && npx cdk synth --no-staging --quiet --no-bundling > /dev/null 2>&1 \
		&& echo "$(GREEN)CDK synth passed.$(NC)" \
		|| (echo "$(RED)ERROR: CDK synth failed! Run 'cd cdk && npx cdk synth' to see details.$(NC)" && exit 1)

emit-profile: ## Resolve the selected auth_profile → .auth-profile-resolved.json (preview the artifact synth reads)
	@python scripts/deploy/run_emit.py --backend cdk

test: ## Run the pytest suite
	python -m pytest tests/

bump-version: ## Bump version (usage: make bump-version VERSION=0.7.0)
ifndef VERSION
	$(error Usage: make bump-version VERSION=0.7.0)
endif
	@./scripts/dev/bump-version.sh $(VERSION)

generate-types: ## Generate TS + Python types from JSON Schema
	@./scripts/dev/generate-types.sh

package: ## Package clean zip for external sharing
	@./scripts/dev/package-release.sh

check-types: ## Verify generated types are up-to-date (CI)
	@./scripts/dev/generate-types.sh
	@if ! git diff --quiet $(GENERATED_TYPES); then \
		echo "$(RED)ERROR: Generated types are stale! Run 'make generate-types' and commit.$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)Generated types are up-to-date.$(NC)"

# ── Code Quality ──────────────────────────────────────────────────────────────

lint: ruff-lint format eslint prettier ## Auto-fix all linting issues

ruff-lint: ## Run ruff linter with auto-fix
	ruff check --fix

format: ## Format Python code
	ruff format

eslint: ## Run ESLint on frontend with auto-fix
	cd frontend && npx eslint --fix src/

prettier: ## Run Prettier on frontend
	cd frontend && npx prettier --write "src/**/*.{ts,tsx,js,jsx,css,json}"

lint-cicd: ## CI lint (check-only, no auto-fix)
	@echo "Running code quality checks..."
	@if ! ruff check; then \
		echo "$(RED)ERROR: Ruff linting failed!$(NC)"; \
		echo "$(YELLOW)Please run 'make ruff-lint' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@if ! ruff format --check; then \
		echo "$(RED)ERROR: Code formatting check failed!$(NC)"; \
		echo "$(YELLOW)Please run 'make format' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@cd frontend && if ! npx eslint src/; then \
		echo "$(RED)ERROR: ESLint check failed!$(NC)"; \
		echo "$(YELLOW)Please run 'make eslint' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@cd frontend && if ! npx prettier --check "src/**/*.{ts,tsx,js,jsx,css,json}"; then \
		echo "$(RED)ERROR: Prettier formatting check failed!$(NC)"; \
		echo "$(YELLOW)Please run 'make prettier' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)All code quality checks passed!$(NC)"
