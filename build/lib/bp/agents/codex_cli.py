"""The ``codex exec`` backend.

Everything substantive — prompt file, process group, timeout, JSON extraction —
lives in :class:`bp.agents.claude_cli.SubprocessBackend`. This file exists to
name the command and to be the place a user looks when the Codex CLI changes
its flags. The command is overridable per role in ``bp.yaml``
(``options.command``) precisely so that a flag change does not require editing
Python.

The decomposer defaults to this backend in the shipped configuration, following
the brief: putting the decomposition and the checking on models from different
families means the model that proposed a reduction is not the one asked whether
it holds.
"""

from __future__ import annotations

from .claude_cli import SubprocessBackend


class CodexCLIBackend(SubprocessBackend):
    name = "codex_cli"
    #: ``--skip-git-repo-check`` because the prompt arrives on stdin and the tool
    #: otherwise refuses to run outside a trusted directory. It is reading a
    #: prompt, not touching the repository.
    default_command = ("codex", "exec", "--skip-git-repo-check", "--model", "{model}")
