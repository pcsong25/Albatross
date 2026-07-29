"""Reading and writing node files.

Node files are hand-edited, so the writer's job is to change exactly what it was
asked to change and leave every comment, quote style and key order alone. That is
why the frontmatter is parsed with ``ruamel.yaml`` in round-trip mode and each
node keeps its parsed :class:`~ruamel.yaml.comments.CommentedMap` alongside the
validated :class:`~bp.model.Node`. The pydantic model is what the rest of the
system reasons about; the CommentedMap is what gets written back.

All writes are atomic: a temporary file in the same directory, ``fsync``, then
``os.replace``. A crash mid-write leaves the old file intact, never a half one.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any, Iterable

import frontmatter
from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import SingleQuotedScalarString

from .model import COMPUTED_FIELDS, VERIFICATION_FIELDS, Node
from .paths import Project

FM_BOUNDARY = re.compile(r"^-{3,}\s*$", re.MULTILINE)

#: Key order used when *creating* a file. Existing files keep whatever order
#: their author chose.
FRONTMATTER_ORDER = [
    "id",
    "role",
    "target",
    "children",
    "strategy",
    "difficulty",
    "lifecycle",
    "local_status",
    "status_reason",
    "flags",
    "hypotheses",
    "uses",
    "global_status",
    "support",
    "blocked_by",
    "statement_hash",
    "verified_against",
    "stale",
]

COMPUTED_BANNER = (
    "--- computed fields: written by `bp sweep`. Never edit them, and never let "
    "an agent write them. ---"
)


class LoadError(Exception):
    """A node file that cannot be turned into a :class:`Node`.

    Carries the path so ``bp check`` can report it as a diagnostic instead of a
    traceback: one unparseable file should not hide the state of the other
    forty.
    """

    def __init__(self, path: Path, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def _represent_none(dumper, _data):
    """Write ``null`` rather than an empty value.

    ``strategy:`` with nothing after it is valid YAML and means the same thing,
    but ``strategy: null`` is what the author wrote and what reads as deliberate.
    """
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    y.representer.add_representer(type(None), _represent_none)
    return y


class RuamelHandler(frontmatter.YAMLHandler):
    """python-frontmatter's splitter, ruamel's parser.

    We want frontmatter's delimiter handling and ruamel's comment preservation,
    so the handler keeps the former and replaces the latter.
    """

    def load(self, fm: str, **kwargs: Any) -> Any:
        return _yaml().load(fm) or CommentedMap()

    def export(self, metadata: Any, **kwargs: Any) -> str:
        return dump_frontmatter(metadata).rstrip("\n")


def quoted(value: Any) -> Any:
    """Force a scalar to be written as a quoted YAML string.

    Used for hashes: an unquoted hex digest can be a valid YAML float, and a
    silently-numeric hash breaks staleness in the dangerous direction.
    """
    if isinstance(value, str):
        return SingleQuotedScalarString(value)
    return value


def dump_frontmatter(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def compose(meta: Any, body: str) -> str:
    """Reassemble a node file from frontmatter and body."""
    fm = dump_frontmatter(meta).rstrip("\n")
    body = body.strip("\n")
    return f"---\n{fm}\n---\n\n{body}\n"


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so that readers see either the old file or the
    new one, never a partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    except OSError:  # pragma: no cover - not every filesystem allows this
        pass
    finally:
        os.close(dir_fd)


def parse_node(text: str, path: Path) -> Node:
    """Parse one node file's text into a validated :class:`Node`."""
    if not FM_BOUNDARY.match(text.lstrip("﻿")):
        raise LoadError(path, "file does not start with a `---` frontmatter block")

    # frontmatter.loads() would rebuild the metadata as a plain dict via **kwargs
    # and throw away ruamel's comments, so use the handler's splitter and parse
    # the block ourselves.
    handler = RuamelHandler()
    try:
        fm, content = handler.split(text)
    except ValueError as exc:
        raise LoadError(path, f"unterminated frontmatter block: {exc}") from exc
    try:
        meta = handler.load(fm)
    except Exception as exc:
        raise LoadError(path, f"frontmatter is not valid YAML: {exc}") from exc

    if not isinstance(meta, dict):
        raise LoadError(path, "frontmatter must be a YAML mapping")

    data = {k: _plain(v) for k, v in meta.items()}
    data["body"] = content.strip("\n")
    data["path"] = path
    try:
        node = Node(**data)
    except ValidationError as exc:
        raise LoadError(path, _format_validation_error(exc)) from exc

    node._raw = meta
    return node


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"]) or "<root>"
        parts.append(f"{loc}: {e['msg']}")
    return "; ".join(parts)


def _plain(value: Any) -> Any:
    """Strip ruamel's round-trip wrappers so pydantic sees plain builtins."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    return value


def raw(node: Node) -> CommentedMap:
    """The node's frontmatter as parsed, for writing back."""
    if node._raw is None:
        node._raw = CommentedMap()
    return node._raw


def read_node(path: Path) -> Node:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError(path, str(exc)) from exc
    return parse_node(text, path)


def iter_node_paths(project: Project) -> Iterable[Path]:
    if not project.nodes_dir.is_dir():
        return []
    return sorted(p for p in project.nodes_dir.rglob("*.md") if p.is_file())


def load_nodes(project: Project) -> tuple[list[Node], list[LoadError]]:
    """Read every node file. Returns what loaded and what did not."""
    nodes: list[Node] = []
    errors: list[LoadError] = []
    for path in iter_node_paths(project):
        try:
            nodes.append(read_node(path))
        except LoadError as exc:
            errors.append(exc)
    return nodes, errors


def node_path(project: Project, node_id: str) -> Path:
    return project.nodes_dir / f"{node_id}.md"


def write_node(node: Node, path: Path | None = None) -> Path:
    """Write a node back to disk from its CommentedMap plus current body."""
    target = path or node.path
    if target is None:
        raise ValueError(f"node {node.id} has no path to write to")
    atomic_write(target, compose(raw(node), node.body))
    node.path = target
    return target


def set_frontmatter(node: Node, key: str, value: Any) -> None:
    """Set one frontmatter key in the CommentedMap, keeping declared order for
    keys the file does not have yet."""
    m = raw(node)
    if key in m:
        m[key] = value
        return
    if key in FRONTMATTER_ORDER:
        after = _preceding_key(m, key)
        if after is not None:
            m.insert(list(m.keys()).index(after) + 1, key, value)
            return
    m[key] = value


def _preceding_key(m: CommentedMap, key: str) -> str | None:
    idx = FRONTMATTER_ORDER.index(key)
    for prior in reversed(FRONTMATTER_ORDER[:idx]):
        if prior in m:
            return prior
    return None


def persist_computed(node: Node) -> bool:
    """Write the derived fields into the file. The *only* writer of them.

    Returns True when the file changed, so callers can avoid rewriting a graph
    that is already up to date.
    """
    m = raw(node)
    updates = {
        "global_status": node.global_status,
        "support": list(node.support),
        "blocked_by": list(node.blocked_by),
        "statement_hash": quoted(node.statement_hash),
        "stale": node.stale,
    }
    changed = False
    banner = "global_status" not in m
    for key, value in updates.items():
        if _plain(m.get(key, _MISSING)) != value:
            set_frontmatter(node, key, value)
            changed = True
    if banner and "global_status" in m:
        try:
            m.yaml_set_comment_before_after_key("global_status", before=COMPUTED_BANNER)
        except AttributeError:  # pragma: no cover - a plain dict, no comments
            pass
    if changed:
        write_node(node)
    return changed


def computed_on_disk(node: Node) -> dict[str, Any]:
    m = raw(node)
    return {k: _plain(m.get(k)) for k in sorted(COMPUTED_FIELDS)}


def computed_in_memory(node: Node) -> dict[str, Any]:
    return {
        "blocked_by": list(node.blocked_by),
        "global_status": node.global_status,
        "stale": node.stale,
        "statement_hash": node.statement_hash,
        "support": list(node.support),
    }


class _Missing:
    def __eq__(self, other: object) -> bool:  # pragma: no cover - sentinel
        return False


_MISSING = _Missing()

__all__ = [
    "LoadError",
    "atomic_write",
    "compose",
    "computed_in_memory",
    "computed_on_disk",
    "load_nodes",
    "node_path",
    "parse_node",
    "persist_computed",
    "raw",
    "read_node",
    "set_frontmatter",
    "write_node",
    "COMPUTED_FIELDS",
    "VERIFICATION_FIELDS",
]
