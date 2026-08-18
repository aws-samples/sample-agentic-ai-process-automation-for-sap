#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Usage:
#   python scripts/setup.py               # interactive
#   python scripts/setup.py --skip-deploy # generate config only
"""First-time bootstrap wizard for the ERP Agent platform."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import questionary
from colorama import Fore, Style
from colorama import init as colorama_init

colorama_init()

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT_DIR / "scripts"
CDK_DIR = ROOT_DIR / "cdk"
CONFIG_FILE = CDK_DIR / "config.yaml"
CONFIG_TEMPLATE = CDK_DIR / "config.yaml.example"

C, G, Y, R, NC = Fore.CYAN, Fore.GREEN, Fore.YELLOW, Fore.RED, Style.RESET_ALL


def info(msg: str) -> None:
    print(f"{C}ℹ{NC}  {msg}")


def success(msg: str) -> None:
    print(f"{G}✓{NC}  {msg}")


def warn(msg: str) -> None:
    print(f"{Y}⚠{NC}  {msg}")


def fail(msg: str) -> None:
    print(f"{R}✗{NC}  {msg}")
    sys.exit(1)


def run(cmd: list[str], cwd: Path | None = None, tail: int | None = None) -> str:
    """Run a command, streaming or capturing. Returns stdout (stripped)."""
    if tail is not None:
        # Capture combined output, print only the last `tail` lines.
        proc = subprocess.run(
            cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        lines = proc.stdout.splitlines()
        print("\n".join(lines[-tail:]))
        if proc.returncode != 0:
            fail(f"Command failed: {' '.join(cmd)}")
        return proc.stdout.strip()
    proc = subprocess.run(cmd, cwd=cwd, check=True)
    return ""


def capture(cmd: list[str]) -> str | None:
    """Run a command, return stripped stdout, or None on any failure."""
    try:
        out = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def aws_region() -> str:
    return capture(["aws", "configure", "get", "region"]) or "us-east-1"


def confirm_target() -> None:
    """Confirm the AWS account + region before an irreversible deploy."""
    account = capture(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    )
    arn = capture(
        ["aws", "sts", "get-caller-identity", "--query", "Arn", "--output", "text"]
    )
    region_set = capture(["aws", "configure", "get", "region"])
    region = region_set or "us-east-1"

    print()
    info(f"Deploy target — account={account}, region={region}")
    info(f"  identity: {arn}")
    if not region_set:
        warn(
            "No region configured — defaulting to us-east-1. Set AWS_REGION or run 'aws configure' to change."
        )

    if not questionary.confirm(
        f"Deploy all stacks to account {account} ({region})?", default=False
    ).ask():
        fail("Deployment cancelled — no changes made.")
    print()


# Prerequisites


def check_prereqs() -> None:
    info("Checking prerequisites...")
    missing = [
        c for c in ("node", "npm", "aws", "python3", "pip") if not shutil.which(c)
    ]

    if not shutil.which("docker") and not shutil.which("finch"):
        info(
            "No container runtime found (not required — only needed for deployment_type: docker)"
        )

    if not shutil.which("cdk"):
        warn("CDK CLI not found. Installing globally...")
        run(["npm", "install", "-g", "aws-cdk"])

    node_ver = capture(["node", "-v"]) or "v0"
    node_major = int(re.sub(r"[^\d.]", "", node_ver).split(".")[0] or 0)
    if node_major < 20:
        fail(f"Node.js 20+ required (found {node_ver})")

    if capture(["aws", "sts", "get-caller-identity"]) is None:
        fail("AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE.")

    if missing:
        for c in missing:
            warn(f"Missing: {c}")
        fail("Install missing prerequisites and retry.")

    account = capture(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    )
    success(f"Prerequisites OK — account={account}, region={aws_region()}")
    print()


# Config Generation


def _valid_stack_name(name: str) -> bool | str:
    if not name:
        return "Stack name is required."
    if len(name) > 35:
        return "Max 35 characters."
    if "_" in name:
        return "No underscores — use hyphens."
    return True


def _valid_email(value: str) -> bool | str:
    # Blank is allowed (both emails are optional); validate only when provided.
    if not value:
        return True
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        return "Enter a valid email address (or leave blank)."
    return True


def _sub_line(text: str, key: str, value: str, indent: str = "") -> str:
    """Replace a `key: ...` line, preserving leading indent."""
    return re.sub(
        rf"(?m)^{re.escape(indent)}{re.escape(key)}:.*$",
        f"{indent}{key}: {value}",
        text,
        count=1,
    )


# Matches the commented `# demo:` block and its `#`-prefixed body only, so the
# explanatory header above it is left untouched.
_DEMO_BLOCK_RE = re.compile(r"(?m)^# demo:\n(?:^#.*\n)*")


def _apply_demo_choice(text: str, ticketing: bool, test_data: bool) -> str:
    """Swap the commented demo block for an active one with the chosen sub-flags.
    No-op when neither is selected (leaves it commented — production-clean default)."""
    if not (ticketing or test_data):
        return text
    active = (
        "demo:\n"
        f"  ticketing:\n    enabled: {'true' if ticketing else 'false'}\n"
        f"  test_data:\n    enabled: {'true' if test_data else 'false'}\n"
    )
    return _DEMO_BLOCK_RE.sub(active, text, count=1)


def generate_config() -> str:
    if CONFIG_FILE.exists():
        warn("config.yaml already exists.")
        if not questionary.confirm("Overwrite?", default=False).ask():
            info("Keeping existing config.yaml")
            return read_config_key(CONFIG_FILE, "stack_name_base") or ""

    info("Generating config.yaml...")
    print()

    stack_name = questionary.text(
        "Stack name (max 35 chars)", default="my-erp-agent", validate=_valid_stack_name
    ).ask()
    admin_email = questionary.text(
        "Admin email (auto-creates Cognito user, blank to skip)", validate=_valid_email
    ).ask()
    ses_email = questionary.text(
        "SES sender email (blank to skip for now)", validate=_valid_email
    ).ask()

    # Two independent, opt-in demo features (both off = clean production base).
    demo = questionary.checkbox(
        "Enable demo features? (space to toggle, enter to confirm — leave blank for none)",
        choices=[
            questionary.Choice(
                "Ticketing — tickets table + /tickets API + Tickets tab (ITSM stand-in)",
                value="ticketing",
            ),
            questionary.Choice(
                "Test data — sample SAP-case generator + Test Data tab",
                value="test_data",
            ),
        ],
    ).ask()

    if stack_name is None or demo is None:  # Ctrl-C / ESC
        fail("Setup cancelled.")

    text = CONFIG_TEMPLATE.read_text()
    text = _sub_line(text, "stack_name_base", stack_name)
    if admin_email:
        text = _sub_line(text, "admin_user_email", admin_email)
    if ses_email:
        # Uncomment the notification block and set the sender address.
        text = re.sub(r"(?m)^#\s*(notification:)\s*$", r"\1", text)
        text = re.sub(r"(?m)^#\s*(channel: ses).*$", r"  \1", text)
        text = re.sub(
            r"(?m)^#\s*ses_sender_email:.*$", f"  ses_sender_email: {ses_email}", text
        )
    text = _apply_demo_choice(text, "ticketing" in demo, "test_data" in demo)
    CONFIG_FILE.write_text(text)

    success(f"Wrote {CONFIG_FILE}")
    print()
    return stack_name


def read_config_key(path: Path, key: str, indent: str = "") -> str | None:
    m = re.search(
        rf"(?m)^{re.escape(indent)}{re.escape(key)}:[ \t]*(.*)$", path.read_text()
    )
    if not m:
        return None
    return m.group(1).split("#", 1)[0].strip() or None


# SES Setup


def setup_ses() -> None:
    region = aws_region()
    sender = read_config_key(CONFIG_FILE, "ses_sender_email", indent="  ")
    if not sender:
        info("No ses_sender_email in config.yaml — skipping SES setup.")
        return

    info(f"Setting up SES sender identity: {sender}")

    def verified() -> bool:
        out = capture(
            [
                "aws",
                "sesv2",
                "get-email-identity",
                "--email-identity",
                sender,
                "--region",
                region,
                "--query",
                "VerifiedForSendingStatus",
                "--output",
                "text",
            ]
        )
        return out == "True"

    if verified():
        success(f"SES identity {sender} already verified.")
        return

    subprocess.run(
        [
            "aws",
            "sesv2",
            "create-email-identity",
            "--email-identity",
            sender,
            "--region",
            region,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    warn(f"Verification email sent to {sender} — click the link to verify.")
    print()
    questionary.press_any_key_to_continue(
        "Press any key after you've clicked the verification link..."
    ).ask()

    if verified():
        success(f"SES identity {sender} verified!")
    else:
        warn(
            "SES identity not yet verified. You can verify later — deployment will continue."
        )

    prod = capture(
        [
            "aws",
            "sesv2",
            "get-account",
            "--region",
            region,
            "--query",
            "ProductionAccessEnabled",
            "--output",
            "text",
        ]
    )
    if prod != "True":
        warn("SES is in sandbox mode — you can only send to verified email addresses.")
        info(
            f"Request production access at: https://{region}.console.aws.amazon.com/ses/home#/account"
        )
    print()


# Deploy


def deploy_infra() -> None:
    info("Installing CDK dependencies...")
    run(["npm", "install", "--silent"], cwd=CDK_DIR)

    account = capture(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    )
    region = aws_region()

    info(f"Bootstrapping CDK (account={account}, region={region})...")
    run(["cdk", "bootstrap", f"aws://{account}/{region}"], cwd=CDK_DIR, tail=5)

    info("Deploying all stacks (this takes 10-20 minutes)...")
    run(
        [
            "cdk",
            "deploy",
            "--all",
            "--require-approval",
            "never",
            "--progress",
            "events",
        ],
        cwd=CDK_DIR,
        tail=30,
    )
    success("Infrastructure deployed!")
    print()


def deploy_frontend() -> None:
    info("Deploying frontend...")
    run(["python3", "scripts/deploy/deploy-frontend.py"], cwd=ROOT_DIR)
    success("Frontend deployed!")
    print()


# Next Steps


def print_next_steps() -> None:
    region = aws_region()
    print(f"""
{C}═══════════════════════════════════════════════════════════════{NC}
{G}  Deployment complete!{NC}
{C}═══════════════════════════════════════════════════════════════{NC}

{Y}── SES Setup (required for email workflows) ──{NC}

  The agent sends inquiry emails and receives approval replies via SES.
  SES starts in sandbox mode — you can only send to verified addresses.

  Option A — Custom domain (recommended for full send+receive):
     If you own a domain with a Route 53 hosted zone:
     {C}./scripts/ops/setup-ses-domain.sh mail.example.com{NC}
     This automates DKIM, MX, and config.yaml updates in one command.

  Option B — Individual email verification (quick start):
     {C}aws ses verify-email-identity --email-address <your-sender-email> --region {region}{NC}
     Then click the verification link in your inbox.

{Y}── Verify Deployment ──{NC}

  Run the built-in test scripts:
     {C}cd test-scripts{NC}
     {C}python3 test-gateway.py{NC}    # Verify Gateway tools are reachable
     {C}python3 test-agent.py{NC}      # Invoke the agent with a test case
     {C}python3 test-memory.py{NC}     # Verify session memory works

  Check CloudWatch logs:
     Log group: /aws/bedrock-agentcore/runtimes/<agent-name>-DEFAULT

{Y}── SAP Connectivity ──{NC}

  The agent needs SAP OData API access. Configure in config.yaml:
  1. Set sap.base_url to your SAP OData endpoint
  2. Store SAP credentials in Secrets Manager (CDK created the placeholder)
  3. Redeploy: {C}cd cdk && cdk deploy --all{NC}

  For testing without SAP, the gateway tools will return mock responses
  when SAP_BASE_URL is not configured.

{Y}── Frontend ──{NC}

  The Amplify URL is in the CDK outputs. Check Cognito for your admin
  credentials (if you provided admin_user_email during setup).
""")


# Main


def main() -> None:
    parser = argparse.ArgumentParser(
        description="First-time bootstrap for the ERP Agent platform."
    )
    parser.add_argument(
        "--skip-deploy", action="store_true", help="Generate config only, skip deploy."
    )
    args = parser.parse_args()

    print(f"""
{C}╔═══════════════════════════════════════════════════╗{NC}
{C}║  ERP Agent Platform — First-Time Bootstrap       ║{NC}
{C}╚═══════════════════════════════════════════════════╝{NC}
""")

    check_prereqs()
    generate_config()
    setup_ses()

    if args.skip_deploy:
        info("Skipping deployment (--skip-deploy). Run manually:")
        print("  cd cdk && cdk deploy --all")
        print("  python3 scripts/deploy/deploy-frontend.py")
        print_next_steps()
        return

    confirm_target()
    deploy_infra()

    # sync-sap-secret.sh hard-fails when sap.base_url is unset, so only run it
    # when SAP is actually configured — otherwise a no-SAP deploy never reaches
    # deploy_frontend().
    if read_config_key(CONFIG_FILE, "base_url", indent="  "):
        info("Syncing SAP credentials to Secrets Manager...")
        run(["bash", str(SCRIPT_DIR / "sync-sap-secret.sh")])
    else:
        info(
            "No sap.base_url in config.yaml — skipping SAP sync (optional; run 'make sync-sap-secret' later)."
        )

    deploy_frontend()
    print_next_steps()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fail("Setup cancelled.")
