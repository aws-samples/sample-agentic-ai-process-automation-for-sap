# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Guards on how the launcher passes payloads to mutating AWS calls.

Every mutating call routes through `Aws._write_via_file`, whose contract has two
halves: the payload must reach the CLI through a file rather than argv, because
argv is world-readable via `ps`; and the file reference must be one the CLI can
actually parse. The second half is not theoretical — the helper previously used
`file:///dev/stdin`, which aws-cli 2.36 rejects with "Invalid JSON received" for
any input, so all 26 Lambda refreshes failed on a real deploy while the launcher
still reported success.

The refresh exit code is pinned for the same reason: `redeploy` used to discard
it, so a run where every function failed to update still exited 0.
"""

from __future__ import annotations

import json
from pathlib import Path

from launcher import awsx, shell


class _Recorder:
    """Stands in for `shell.run`, capturing argv and reading the payload file."""

    def __init__(self, *, ok: bool = True, output: str = "{}") -> None:
        self.ok = ok
        self.output = output
        self.argv: list[str] = []
        self.stdin_text: str | None = None
        self.payload_text: str | None = None
        self.payload_mode: int | None = None

    def __call__(self, argv, **kwargs):
        self.argv = list(argv)
        self.stdin_text = kwargs.get("stdin_text")
        for token in self.argv:
            if token.startswith("file://"):
                path = Path(token.removeprefix("file://"))
                # Read inside the call: the helper deletes the temp dir on return.
                self.payload_text = path.read_text(encoding="utf-8")
                self.payload_mode = path.stat().st_mode & 0o777
        return shell.Result(code=0 if self.ok else 1, output=self.output)


def _aws_with(monkeypatch, recorder: _Recorder) -> awsx.Aws:
    monkeypatch.setattr(shell, "run", recorder)
    aws = awsx.Aws(region="us-east-1")
    # Secret writes prefer boto3 when it imports; the CLI fallback is the path
    # this file covers, so force it rather than depending on boto3's absence.
    monkeypatch.setattr(aws, "_boto3", lambda service: None)
    return aws


def test_payload_reaches_the_cli_as_a_readable_file(monkeypatch) -> None:
    recorder = _Recorder()
    aws = _aws_with(monkeypatch, recorder)

    aws.lambda_set_environment("fn", {"A": "1"})

    assert recorder.payload_text is not None, "payload never reached a file"
    assert json.loads(recorder.payload_text) == {
        "FunctionName": "fn",
        "Environment": {"Variables": {"A": "1"}},
    }


def test_payload_is_not_passed_on_stdin(monkeypatch) -> None:
    """`file:///dev/stdin` is unparseable in aws-cli 2.36 — the regression."""
    recorder = _Recorder()
    aws = _aws_with(monkeypatch, recorder)

    aws.lambda_set_environment("fn", {"A": "1"})

    assert recorder.stdin_text is None
    assert "file:///dev/stdin" not in recorder.argv


def test_payload_never_appears_in_argv(monkeypatch) -> None:
    recorder = _Recorder()
    aws = _aws_with(monkeypatch, recorder)

    aws.secret_put_string("secret-id", "s3cr3t")

    assert "s3cr3t" not in " ".join(recorder.argv)
    assert json.loads(recorder.payload_text or "{}")["SecretString"] == "s3cr3t"


def test_payload_file_is_owner_only(monkeypatch) -> None:
    recorder = _Recorder()
    aws = _aws_with(monkeypatch, recorder)

    aws.secret_put_string("secret-id", "s3cr3t")

    assert recorder.payload_mode == 0o600


def test_a_failed_write_raises(monkeypatch) -> None:
    recorder = _Recorder(ok=False, output="An error occurred (ParamValidation)")
    aws = _aws_with(monkeypatch, recorder)

    try:
        aws.lambda_set_environment("fn", {"A": "1"})
    except awsx.AwsError as exc:
        assert "ParamValidation" in (exc.hint or "")
    else:  # pragma: no cover - the assertion below reports the miss
        raise AssertionError("a failed CLI call must raise")


def test_redeploy_returns_the_refresh_failure(monkeypatch) -> None:
    """A refresh that fails every function must not be reported as success."""
    from launcher.commands import guided

    monkeypatch.setattr(guided.target, "confirm", lambda ctx: None)
    monkeypatch.setattr(guided.infra, "deploy", lambda ctx: None)
    monkeypatch.setattr(guided.frontend, "run", lambda ctx: 0)
    monkeypatch.setattr(guided, "_summary", lambda ctx, **kwargs: None)
    monkeypatch.setattr(guided.refresh, "run", lambda ctx, quiet=False: 4)

    assert guided.redeploy(object()) == 4
