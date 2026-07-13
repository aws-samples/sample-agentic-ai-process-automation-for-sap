# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Lambda function to package agent code for ZIP deployment (Terraform).

Downloads ARM64 wheels, extracts them, bundles with agent code,
and uploads to S3. Invoked directly by Terraform (no CloudFormation
Custom Resource protocol).

Core packaging logic mirrors cdk/lambdas/zip-packager/index.py
but uses a simple request/response interface instead of the CF
Custom Resource callback pattern.
"""

import base64
import logging
import os
import subprocess  # nosec B404
import sys
import tempfile
import zipfile
from pathlib import Path

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")


def download_wheels(requirements: list[str], download_dir: Path) -> None:
    """
    Download ARM64 Linux wheels for the given requirements.

    Uses pip download with platform targeting to fetch pre-built wheels
    for the Lambda runtime architecture (aarch64/ARM64, Python 3.12).

    Args:
        requirements: List of pip package specifiers.
        download_dir: Directory to download wheel files into.
    """
    logger.info(f"Downloading wheels for: {requirements}")

    req_file = download_dir / "requirements.txt"
    req_file.write_text("\n".join(requirements))

    subprocess.run(  # nosec B603 — args are static strings  # nosemgrep: dangerous-subprocess-use-audit
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "-r",
            str(req_file),
            "--platform",
            "manylinux2014_aarch64",
            "--python-version",
            "312",
            "--only-binary=:all:",
            "-d",
            str(download_dir),
            "--quiet",
        ],
        check=True,
    )

    # Also download OpenTelemetry (required by AgentCore Runtime)
    subprocess.run(  # nosec B603 — args are static strings  # nosemgrep: dangerous-subprocess-use-audit
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "aws-opentelemetry-distro",
            "--platform",
            "manylinux2014_aarch64",
            "--python-version",
            "312",
            "--only-binary=:all:",
            "-d",
            str(download_dir),
            "--quiet",
        ],
        check=True,
    )


def extract_wheels(download_dir: Path, package_dir: Path) -> None:
    """
    Extract all wheel files to the package directory.

    Args:
        download_dir: Directory containing downloaded .whl files.
        package_dir: Directory to extract wheel contents into.
    """
    for wheel in download_dir.glob("*.whl"):
        logger.info(f"Extracting: {wheel.name}")
        with zipfile.ZipFile(wheel, "r") as whl:
            whl.extractall(package_dir)


def create_otel_wrapper(package_dir: Path) -> None:
    """
    Create the opentelemetry-instrument wrapper script.

    This script is used as the entry point for AgentCore Runtime
    to enable distributed tracing via OpenTelemetry.

    Args:
        package_dir: Root package directory.
    """
    bin_dir = package_dir / "bin"
    bin_dir.mkdir(exist_ok=True)

    script = bin_dir / "opentelemetry-instrument"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "from opentelemetry.instrumentation.auto_instrumentation import run\n"
        "run()\n"
    )


def create_deployment_zip(package_dir: Path, output_path: Path) -> None:
    """
    Create the deployment ZIP file with proper Unix permissions.

    Sets executable permissions (755) for files in bin/ and standard
    permissions (644) for all other files. Directory entries get 755.

    Args:
        package_dir: Directory to zip.
        output_path: Output ZIP file path.
    """
    logger.info(f"Creating deployment ZIP: {output_path}")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                arcname = str(dir_path.relative_to(package_dir)) + "/"
                info = zipfile.ZipInfo(arcname)
                info.external_attr = 0o755 << 16
                zipf.writestr(info, "")

            for file_name in files:
                file_path = Path(root) / file_name
                arcname = str(file_path.relative_to(package_dir))
                info = zipfile.ZipInfo(arcname)
                if arcname.startswith("bin/"):
                    info.external_attr = 0o755 << 16
                else:
                    info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zipf.writestr(info, file_path.read_bytes())


def handler(event: dict, context) -> dict:
    """
    Lambda handler for Terraform-invoked packaging.

    Accepts a direct invocation payload (not CloudFormation Custom Resource).
    Downloads ARM64 wheels, bundles agent code, creates a deployment ZIP,
    and uploads to S3.

    Args:
        event: Invocation payload with keys:
            - bucket_name: S3 bucket for the deployment package
            - object_key: S3 object key (e.g., "deployment_package.zip")
            - requirements: List of pip package specifiers
            - agent_code: Dict mapping file paths to base64-encoded content
        context: Lambda context (unused).

    Returns:
        Dict with "status" ("SUCCESS" or "FAILED"), "s3_uri", and optionally "error".
    """
    logger.info(f"Event keys: {list(event.keys())}")

    try:
        bucket_name = event["bucket_name"]
        object_key = event["object_key"]
        requirements = event["requirements"]
        agent_code = event["agent_code"]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            download_dir = tmp_path / "wheels"
            package_dir = tmp_path / "package"
            download_dir.mkdir()
            package_dir.mkdir()

            download_wheels(requirements, download_dir)
            extract_wheels(download_dir, package_dir)

            create_otel_wrapper(package_dir)

            for filename, content_b64 in agent_code.items():
                file_path = package_dir / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(base64.b64decode(content_b64))

            zip_path = tmp_path / "deployment_package.zip"
            create_deployment_zip(package_dir, zip_path)

            s3_uri = f"s3://{bucket_name}/{object_key}"
            logger.info(f"Uploading to {s3_uri}")
            s3.upload_file(str(zip_path), bucket_name, object_key)

        return {
            "status": "SUCCESS",
            "s3_uri": s3_uri,
        }

    except Exception as e:
        logger.exception("Failed to package agent")
        return {
            "status": "FAILED",
            "error": str(e),
        }
