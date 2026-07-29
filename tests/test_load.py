"""Node files are hand-edited, so reading and writing them must be lossless."""

from __future__ import annotations

import pytest

from bp import load
from bp.model import Node, set_section, split_sections

SAMPLE = """---
id: demo.node
role: lemma
children: []

# a comment the author wrote and expects to keep
hypotheses:
  - {id: H1, tex: "s > 3/2"}
uses: {}
---

## Statement

Let $s > 3/2$.

## Proof

Obvious.
"""


def test_round_trip_preserves_comments_and_style(tmp_path):
    path = tmp_path / "demo.node.md"
    path.write_text(SAMPLE, encoding="utf-8")
    node = load.read_node(path)

    assert node.id == "demo.node"
    assert node.hypotheses[0].tex == "s > 3/2"
    assert node.statement_section == "Let $s > 3/2$."

    load.write_node(node)
    after = path.read_text(encoding="utf-8")
    assert "# a comment the author wrote and expects to keep" in after
    assert '{id: H1, tex: "s > 3/2"}' in after


def test_computed_fields_are_written_only_by_persist(tmp_path):
    path = tmp_path / "demo.node.md"
    path.write_text(SAMPLE, encoding="utf-8")
    node = load.read_node(path)
    node.global_status = "proved"
    node.statement_hash = "abc123"
    assert load.persist_computed(node) is True

    reloaded = load.read_node(path)
    assert reloaded.global_status == "proved"
    assert reloaded.statement_hash == "abc123"
    assert load.persist_computed(reloaded) is False
    assert load.COMPUTED_BANNER.split(":")[0] in path.read_text(encoding="utf-8")


def test_hex_hashes_are_quoted_on_write(tmp_path):
    """``896e63762324`` is a valid YAML float. Unquoted, it would come back as
    ``inf`` and compare equal to every other such hash."""
    path = tmp_path / "demo.node.md"
    path.write_text(SAMPLE, encoding="utf-8")
    node = load.read_node(path)
    node.statement_hash = "896e63762324"
    load.persist_computed(node)
    assert "'896e63762324'" in path.read_text(encoding="utf-8")
    assert load.read_node(path).statement_hash == "896e63762324"


def test_unquoted_float_hash_is_refused_not_coerced(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        SAMPLE.replace("uses: {}", "uses: {}\nstatement_hash: 896e63762324"),
        encoding="utf-8",
    )
    with pytest.raises(load.LoadError) as exc:
        load.read_node(path)
    assert "quoted" in str(exc.value)


def test_missing_frontmatter_is_a_load_error(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("# just markdown\n", encoding="utf-8")
    with pytest.raises(load.LoadError):
        load.read_node(path)


def test_invalid_field_is_a_load_error_naming_the_field(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(SAMPLE.replace("role: lemma", "role: haiku"), encoding="utf-8")
    with pytest.raises(load.LoadError) as exc:
        load.read_node(path)
    assert "role" in str(exc.value)


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "out.md"
    load.atomic_write(target, "hello\n")
    assert target.read_text() == "hello\n"
    assert [p.name for p in tmp_path.iterdir()] == ["out.md"]


class TestSections:
    def test_split(self):
        body = "## Statement\n\nS\n\n## Proof\n\nP\n"
        assert split_sections(body) == {"Statement": "S", "Proof": "P"}

    def test_replace_keeps_position(self):
        body = "## Statement\n\nS\n\n## Proof\n\nP\n"
        out = set_section(body, "Statement", "T")
        assert split_sections(out) == {"Statement": "T", "Proof": "P"}

    def test_create_uses_canonical_order(self):
        body = "## Statement\n\nS\n\n## Notes\n\nN\n"
        out = set_section(body, "Proof", "P")
        assert list(split_sections(out)) == ["Statement", "Proof", "Notes"]

    def test_preamble_survives(self):
        body = "Some preamble.\n\n## Statement\n\nS\n"
        out = set_section(body, "Proof", "P")
        assert out.startswith("Some preamble.")


def test_has_proof_ignores_comments_and_whitespace():
    node = Node(id="x", body="## Proof\n\n%  nothing yet\n")
    assert node.has_proof is False
    node = Node(id="x", body="## Proof\n\nAn argument.\n")
    assert node.has_proof is True
