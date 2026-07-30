"""The ``claude -p`` backend, plus the subprocess machinery `codex_cli` shares.

These exist so that a user who pays a flat monthly fee for a coding CLI can run
this system without a metered API key. That is worth real money on a project
that will make thousands of calls, and it is why the whole agent layer is built
around *roles* rather than around one provider.

Three details are not optional:

*The prompt goes to a file, and the file goes to stdin.* Decomposition prompts
carry a node's statement, its ancestors, its notes and a JSON schema. They
exceed the argv limit, and a prompt truncated by the shell fails in a way that
looks like a model error.

*The process runs in its own process group, and a timeout kills the group.* A
CLI tool spawns children; killing only the parent leaves them holding the
terminal and the run hangs where a human is not watching.

*Cost is unknown, and that is reported honestly rather than guessed.* These
backends set ``cost_usd = None`` and record wall time. The budget's call-count
cap is what constrains them.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Sequence

from .base import AgentError, Backend, BackendUnavailable, Completion


class SubprocessBackend(Backend):
    """Shared machinery for headless CLI tools."""

    name = "subprocess"
    reports_cost = False

    #: Argument vector, run with the prompt on stdin. Overridable per role in
    #: ``bp.yaml`` via ``options.command`` — CLI flags drift between releases
    #: and the user should not have to edit Python to keep up.
    default_command: Sequence[str] = ()

    @property
    def command(self) -> list[str]:
        configured = self.options.get("command")
        if configured:
            return [str(part) for part in configured]
        return [part.format(model=self.model) for part in self.default_command]

    def available(self) -> tuple[bool, str]:
        exe = self.command[0]
        if shutil.which(exe) is None:
            return False, (
                f"`{exe}` is not on PATH. Install it, or point this role at an "
                "API backend in bp.yaml"
            )
        return True, ""

    def compose_prompt(self, system: str, user: str) -> str:
        """CLI tools take one prompt, not a system/user pair."""
        return f"{system.strip()}\n\n---\n\n{user.strip()}\n"

    def invoke(self, system: str, user: str, timeout: float) -> Completion:
        prompt = self.compose_prompt(system, user)
        started = time.monotonic()

        with tempfile.NamedTemporaryFile(
            "w", suffix=".prompt.md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(prompt)
            prompt_path = fh.name

        try:
            with open(prompt_path, encoding="utf-8") as stdin:
                proc = subprocess.Popen(
                    self.command,
                    stdin=stdin,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,  # its own process group, to kill cleanly
                    cwd=self.options.get("cwd") or None,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_group(proc)
                    stdout, stderr = proc.communicate()
                    raise AgentError(
                        f"{self.command[0]} did not answer within {timeout:.0f}s; "
                        "the process group was killed"
                    ) from None
        except FileNotFoundError as exc:
            raise BackendUnavailable(f"{self.command[0]} is not installed: {exc}") from exc
        finally:
            try:
                os.unlink(prompt_path)
            except OSError:  # pragma: no cover
                pass

        if proc.returncode != 0:
            raise AgentError(
                f"{self.command[0]} exited {proc.returncode}: "
                f"{(stderr or stdout or '').strip()[:800]}"
            )
        if not (stdout or "").strip():
            raise AgentError(f"{self.command[0]} produced no output")

        return Completion(
            text=stdout,
            cost_usd=None,  # a subscription tool cannot tell us what this cost
            input_tokens=None,
            output_tokens=None,
        )


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: no cover
        proc.kill()


class ClaudeCLIBackend(SubprocessBackend):
    """``claude -p`` in print mode."""

    name = "claude_cli"
    default_command = ("claude", "-p", "--model", "{model}")


    def compose_prompt(self, system: str, user: str) -> str:
        # `claude -p` has no separate system channel, so the two halves are
        # concatenated with a visible rule between them.
        return super().compose_prompt(system, user)
