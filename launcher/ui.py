# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Terminal output and prompting. Standard library only.

Deliberately dependency-free so `python3 launch.py doctor` works on a clean
clone before anything is installed. Colour and Unicode both degrade rather
than mangle: the shell scripts this replaces emitted `echo -e` escapes and
glyphs unconditionally, which corrupts output on non-UTF-8 consoles and in
piped logs.
"""

from __future__ import annotations

import getpass
import os
import shutil
import sys
from collections.abc import Callable, Sequence

from .errors import Cancelled, LauncherError

# ── Capability detection ─────────────────────────────────────────────────


def _supports_colour(stream: object = None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _supports_unicode(stream: object = None) -> bool:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or ""
    if "utf" not in encoding.lower():
        return False
    return True


_COLOUR = _supports_colour()
_UNICODE = _supports_unicode()


class _C:
    """ANSI codes, blanked when the terminal cannot render them."""

    RESET = "\033[0m" if _COLOUR else ""
    BOLD = "\033[1m" if _COLOUR else ""
    DIM = "\033[2m" if _COLOUR else ""
    RED = "\033[31m" if _COLOUR else ""
    GREEN = "\033[32m" if _COLOUR else ""
    YELLOW = "\033[33m" if _COLOUR else ""
    CYAN = "\033[36m" if _COLOUR else ""


_GLYPH = {
    "ok": "✓" if _UNICODE else "[ok]",
    "err": "✗" if _UNICODE else "[!!]",
    "warn": "!" if _UNICODE else "[ !]",
    "info": "·" if _UNICODE else "[..]",
    "arrow": "→" if _UNICODE else "->",
    "rule": "─" if _UNICODE else "-",
}


def width(maximum: int = 78) -> int:
    return min(shutil.get_terminal_size((80, 24)).columns, maximum)


# ── Output ───────────────────────────────────────────────────────────────


def blank() -> None:
    print()


def heading(text: str) -> None:
    """A section banner. Used once per phase, not per line."""
    print()
    print(f"{_C.BOLD}{_C.CYAN}{text}{_C.RESET}")
    print(f"{_C.DIM}{_GLYPH['rule'] * min(len(text), width())}{_C.RESET}")


def step(index: int, total: int, text: str) -> None:
    print()
    print(f"{_C.BOLD}[{index}/{total}] {text}{_C.RESET}")


def ok(text: str) -> None:
    print(f"  {_C.GREEN}{_GLYPH['ok']}{_C.RESET} {text}")


def warn(text: str) -> None:
    print(f"  {_C.YELLOW}{_GLYPH['warn']}{_C.RESET} {text}")


def err(text: str) -> None:
    # Flush stdout first: it is block-buffered when piped while stderr is not,
    # so without this the error appears before the output it belongs after.
    sys.stdout.flush()
    print(f"  {_C.RED}{_GLYPH['err']}{_C.RESET} {text}", file=sys.stderr, flush=True)


def info(text: str) -> None:
    print(f"  {_C.DIM}{_GLYPH['info']}{_C.RESET} {text}")


def detail(text: str) -> None:
    """Indented supporting text — never the primary signal."""
    print(f"    {_C.DIM}{text}{_C.RESET}")


def hint(text: str) -> None:
    print(f"    {_C.CYAN}{_GLYPH['arrow']}{_C.RESET} {text}")


def kv(pairs: Sequence[tuple[str, object]], indent: str = "  ") -> None:
    """Aligned key/value block. Values are stringified as-is."""
    if not pairs:
        return
    pad = max(len(str(k)) for k, _ in pairs)
    for key, value in pairs:
        shown = "(unset)" if value in (None, "") else str(value)
        print(f"{indent}{_C.DIM}{str(key).ljust(pad)}{_C.RESET}  {shown}")


def bullets(items: Sequence[str], indent: str = "    ") -> None:
    for item in items:
        print(f"{indent}{_C.DIM}-{_C.RESET} {item}")


def tail_output(text: str, lines: int = 25, label: str = "output") -> None:
    """Print the last N lines of captured output, clearly fenced."""
    kept = [ln for ln in text.splitlines() if ln.strip()][-lines:]
    if not kept:
        return
    print(f"    {_C.DIM}last {len(kept)} lines of {label}:{_C.RESET}")
    for line in kept:
        print(f"    {_C.DIM}|{_C.RESET} {line}")


# ── Prompting ────────────────────────────────────────────────────────────

Validator = Callable[[str], str | None]
"""Returns an error message, or None when the value is acceptable."""


class Prompter:
    """Interactive input, with an explicit non-interactive contract.

    When `interactive` is false (no TTY, or `--non-interactive`), prompts do not
    hang waiting on stdin: they take the default, and raise when there is no
    safe default. `assume_yes` additionally auto-accepts confirmations — it is
    never applied to destructive confirmations unless the caller opts in.
    """

    def __init__(
        self, *, interactive: bool | None = None, assume_yes: bool = False
    ) -> None:
        if interactive is None:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self.interactive = interactive
        self.assume_yes = assume_yes

    # -- text ------------------------------------------------------------
    def ask(
        self,
        prompt: str,
        *,
        default: str | None = None,
        validate: Validator | None = None,
        allow_empty: bool = False,
    ) -> str:
        suffix = f" [{default}]" if default else ""
        if not self.interactive:
            if default is not None:
                return default
            if allow_empty:
                return ""
            raise LauncherError(
                f"{prompt} has no value and cannot be prompted for in non-interactive mode.",
                hint="Re-run interactively, or supply the value on the command line.",
            )
        while True:
            try:
                raw = input(f"  {_C.BOLD}?{_C.RESET} {prompt}{suffix}: ").strip()
            except EOFError as exc:
                raise Cancelled() from exc
            except KeyboardInterrupt as exc:
                raise Cancelled() from exc
            value = raw or (default or "")
            if not value and not allow_empty:
                err("A value is required.")
                continue
            if validate:
                problem = validate(value)
                if problem:
                    err(problem)
                    continue
            return value

    # -- secret ----------------------------------------------------------
    def ask_secret(self, prompt: str, *, allow_empty: bool = False) -> str:
        """Read a secret without echoing it.

        The value is returned in memory only. Callers must never place it in a
        subprocess argument list, a config file, or the state file.
        """
        if not self.interactive:
            raise LauncherError(
                f"{prompt} cannot be collected in non-interactive mode.",
                hint="Run this step interactively so the secret is never passed as an argument.",
            )
        while True:
            try:
                value = getpass.getpass(f"  {_C.BOLD}?{_C.RESET} {prompt}: ")
            except (EOFError, KeyboardInterrupt) as exc:
                raise Cancelled() from exc
            if not value and not allow_empty:
                err("A value is required.")
                continue
            return value

    # -- yes/no ----------------------------------------------------------
    def confirm(
        self,
        prompt: str,
        *,
        default: bool = False,
        force_prompt: bool = False,
    ) -> bool:
        """Ask a yes/no question.

        `force_prompt` marks a decision too consequential to be satisfied by
        `--yes` — deleting remote objects, for example. Those still require a
        real answer, or an explicit non-interactive refusal.
        """
        if self.assume_yes and not force_prompt:
            print(f"  {_C.BOLD}?{_C.RESET} {prompt} {_C.DIM}(yes, --yes){_C.RESET}")
            return True
        if not self.interactive:
            if force_prompt:
                raise LauncherError(
                    f"{prompt} requires explicit confirmation and cannot be auto-approved.",
                    hint="Re-run this step interactively.",
                    exit_code=130,
                )
            return default
        options = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                raw = (
                    input(f"  {_C.BOLD}?{_C.RESET} {prompt} {options} ").strip().lower()
                )
            except (EOFError, KeyboardInterrupt) as exc:
                raise Cancelled() from exc
            if not raw:
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
            err("Answer y or n.")

    # -- multi-select ----------------------------------------------------
    def select_many(
        self,
        prompt: str,
        options: Sequence[tuple[str, str]],
        *,
        default: Sequence[str] = (),
    ) -> list[str]:
        """Pick zero or more values. `options` is (value, description).

        Numeric entry rather than a cursor UI: it needs no dependency, works
        over SSH and in dumb terminals, and is readable in a transcript.
        """
        if not self.interactive:
            return list(default)
        print(f"  {_C.BOLD}?{_C.RESET} {prompt}")
        for position, (_, description) in enumerate(options, start=1):
            print(f"      {position}) {description}")
        detail("Enter numbers separated by commas, or press Enter for none.")
        while True:
            try:
                raw = input(f"  {_C.BOLD}?{_C.RESET} Selection: ").strip()
            except (EOFError, KeyboardInterrupt) as exc:
                raise Cancelled() from exc
            if not raw:
                return []
            picked: list[str] = []
            bad = False
            for token in raw.replace(" ", "").split(","):
                if not token.isdigit() or not 1 <= int(token) <= len(options):
                    err(f"'{token}' is not one of 1-{len(options)}.")
                    bad = True
                    break
                value = options[int(token) - 1][0]
                if value not in picked:
                    picked.append(value)
            if not bad:
                return picked
