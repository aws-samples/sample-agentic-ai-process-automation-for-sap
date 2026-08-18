# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""`sync-kb` — publish SOPs and SAP API docs, then re-ingest them.

Ported from `sync-knowledge-base.sh`, which ran `aws s3 sync --delete` against
the *bucket root* with no prefix. That deletes every object in the bucket
without a local counterpart — including files an operator uploaded by hand, and
including `knowledge-base/sops-pdf/`, which the script never uploads. The
deletion set is now computed and shown before anything is removed, and the
delete requires its own confirmation that `--yes` cannot satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import state, ui
from ..context import Ctx
from ..errors import EXIT_AWS, AwsError, Cancelled, ConfigError

PHASE = "knowledge-base"

SOPS = "sops"
API_DOCS = "api-docs"


@dataclass(frozen=True)
class Corpus:
    key: str
    label: str
    local_subdir: str
    bucket_param: str
    kb_param: str


CORPORA = (
    Corpus(
        SOPS, "SOPs", "sops", "/{stack}/s3/sops-bucket", "/{stack}/bedrock/sops-kb-id"
    ),
    Corpus(
        API_DOCS,
        "SAP API docs",
        "sap-api-docs",
        "/{stack}/s3/api-docs-bucket",
        "/{stack}/bedrock/api-docs-kb-id",
    ),
)


def _local_keys(directory: Path) -> set[str]:
    """Object keys `aws s3 sync` would create from this directory."""
    if not directory.is_dir():
        return set()
    return {
        str(path.relative_to(directory)).replace("\\", "/")
        for path in directory.rglob("*")
        if path.is_file()
    }


def _sync_one(ctx: Ctx, corpus: Corpus, *, assume_role_env: dict[str, str]) -> bool:
    local_dir = ctx.knowledge_base_dir / corpus.local_subdir
    if not local_dir.is_dir():
        ui.warn(
            f"{corpus.label}: {local_dir.relative_to(ctx.repo_root)} does not exist — skipping."
        )
        return True

    bucket = ctx.aws.ssm_require(
        corpus.bucket_param.format(stack=ctx.stack_base),
        hint="Deploy the infrastructure first.",
    )
    kb_id = ctx.aws.ssm_get(corpus.kb_param.format(stack=ctx.stack_base))

    local = _local_keys(local_dir)
    remote = set(ctx.aws.s3_keys(bucket))
    to_delete = sorted(remote - local)
    to_add = sorted(local - remote)

    ui.blank()
    print(f"  {corpus.label}")
    ui.kv(
        [
            ("source", str(local_dir.relative_to(ctx.repo_root))),
            ("bucket", bucket),
            ("local files", len(local)),
            ("objects in bucket", len(remote)),
            ("new or changed", len(to_add)),
            ("would be deleted", len(to_delete)),
        ],
        indent="    ",
    )

    delete = False
    if to_delete:
        ui.blank()
        ui.warn(
            f"{len(to_delete)} object(s) exist in the bucket with no local counterpart:"
        )
        ui.bullets(to_delete[:20], indent="      ")
        if len(to_delete) > 20:
            ui.detail(f"...and {len(to_delete) - 20} more")
        ui.detail(
            "The bucket is versioned, so a delete leaves a delete marker rather than destroying data."
        )
        ui.blank()
        delete = ctx.prompter.confirm(
            f"Delete these {len(to_delete)} object(s) from {bucket}?",
            default=False,
            force_prompt=True,
        )
        if not delete:
            ui.info(
                "Keeping them — uploading without --delete, so the bucket may hold extra content."
            )

    result = ctx.aws.s3_sync(
        str(local_dir),
        bucket,
        delete=delete,
        env=assume_role_env,
    )
    if not result.ok:
        ui.err(f"{corpus.label}: upload failed (exit {result.code}).")
        ui.tail_output(result.output, lines=15, label="aws s3 sync")
        return False
    ui.ok(f"{corpus.label}: content published.")

    if not kb_id:
        ui.warn(f"{corpus.label}: no knowledge base id in SSM — skipping ingestion.")
        return True

    data_sources = ctx.aws.kb_data_source_ids(kb_id)
    if not data_sources:
        ui.warn(
            f"{corpus.label}: knowledge base {kb_id} has no data sources — skipping ingestion."
        )
        return True
    if len(data_sources) > 1:
        ui.info(
            f"{corpus.label}: {len(data_sources)} data sources; starting ingestion for all of them."
        )

    started = 0
    for data_source_id in data_sources:
        job_id = ctx.aws.kb_start_ingestion(kb_id, data_source_id)
        if job_id:
            started += 1
            ui.ok(f"{corpus.label}: ingestion started ({job_id})")
        else:
            ui.warn(
                f"{corpus.label}: could not start ingestion for data source {data_source_id}."
            )
    return started > 0


def run(ctx: Ctx, *, only: str | None = None) -> int:
    ui.heading("Knowledge base")

    if not ctx.knowledge_base_dir.is_dir():
        raise ConfigError(
            f"{ctx.knowledge_base_dir.relative_to(ctx.repo_root)} is missing from this checkout."
        )

    selected = [corpus for corpus in CORPORA if only in (None, corpus.key)]
    if not selected:
        raise ConfigError(
            f"Unknown corpus '{only}'. Choose from: {', '.join(c.key for c in CORPORA)}."
        )

    # The buckets deny writes to every principal except the sop-admin role, so
    # publishing content requires assuming it first.
    role_arn = f"arn:aws:iam::{ctx.account}:role/{ctx.stack_base}-sop-admin"
    ui.info(
        f"Assuming {ctx.stack_base}-sop-admin — the bucket policies deny writes to anyone else."
    )
    try:
        credentials = ctx.aws.assume_role(role_arn, "launcher-kb-sync")
    except AwsError as exc:
        raise AwsError(
            f"Could not assume {role_arn}.",
            hint=exc.hint
            or "Deploy the infrastructure first, and check the role's trust policy.",
        ) from exc

    state.mark(ctx, PHASE, state.RUNNING)
    ok = True
    for corpus in selected:
        try:
            ok = _sync_one(ctx, corpus, assume_role_env=credentials) and ok
        except Cancelled:
            raise
        except AwsError as exc:
            ui.err(f"{corpus.label}: {exc.message}")
            if exc.hint:
                ui.hint(exc.hint)
            ok = False

    ui.blank()
    if ok:
        ui.ok(
            "Knowledge base synchronised. Ingestion runs asynchronously — allow a few minutes."
        )
        state.mark(ctx, PHASE, state.DONE)
        return 0
    ui.err("Knowledge base sync finished with errors.")
    state.mark(ctx, PHASE, state.FAILED)
    return EXIT_AWS
