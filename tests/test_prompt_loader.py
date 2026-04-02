"""Tests for prompt layer discovery and assembly."""

from __future__ import annotations

from pathlib import Path

from rlm_search.prompt_loader import discover_layers, assemble_prompt


class TestDiscoverLayers:
    """Layer discovery from a directory of numbered markdown files."""

    def test_discovers_and_orders_by_prefix(self, tmp_path: Path):
        (tmp_path / "20-tools.md").write_text("## Tools\nresearch() docs")
        (tmp_path / "00-core.md").write_text("## Core\nREPL rules")
        (tmp_path / "10-domain.md").write_text("## Domain\nI.M.A.M. preamble")

        layers = discover_layers(tmp_path)

        assert [l.name for l in layers] == ["00-core.md", "10-domain.md", "20-tools.md"]
        assert "REPL rules" in layers[0].content
        assert "I.M.A.M. preamble" in layers[1].content

    def test_skips_non_markdown(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("core")
        (tmp_path / "README.txt").write_text("ignore me")
        (tmp_path / "notes.py").write_text("# not a layer")

        layers = discover_layers(tmp_path)
        assert len(layers) == 1
        assert layers[0].name == "00-core.md"

    def test_skips_empty_files(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("real content")
        (tmp_path / "10-empty.md").write_text("   \n  ")

        layers = discover_layers(tmp_path)
        assert len(layers) == 1

    def test_empty_directory(self, tmp_path: Path):
        layers = discover_layers(tmp_path)
        assert layers == []

    def test_missing_directory_returns_empty(self, tmp_path: Path):
        layers = discover_layers(tmp_path / "nonexistent")
        assert layers == []


class TestAssemblePrompt:
    """Assemble a system prompt from discovered layers."""

    def test_concatenates_in_order(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("CORE RULES")
        (tmp_path / "10-domain.md").write_text("DOMAIN RULES")
        (tmp_path / "20-tools.md").write_text("TOOL DOCS")

        result = assemble_prompt(layers_dir=tmp_path)

        assert result.index("CORE RULES") < result.index("DOMAIN RULES")
        assert result.index("DOMAIN RULES") < result.index("TOOL DOCS")

    def test_double_newline_separator(self, tmp_path: Path):
        (tmp_path / "00-a.md").write_text("section a")
        (tmp_path / "10-b.md").write_text("section b")

        result = assemble_prompt(layers_dir=tmp_path)
        assert "section a\n\n\nsection b" not in result  # no triple newlines
        assert "section a\n\nsection b" in result

    def test_empty_dir_returns_empty_string(self, tmp_path: Path):
        result = assemble_prompt(layers_dir=tmp_path)
        assert result == ""


class TestOverrideLayers:
    """Override directory replaces matching default layers."""

    def test_override_replaces_matching_file(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "00-core.md").write_text("default core")
        (defaults / "10-domain.md").write_text("default domain")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "10-domain.md").write_text("custom domain for medical corpus")

        result = assemble_prompt(layers_dir=defaults, overrides_dir=overrides)

        assert "default core" in result
        assert "custom domain for medical corpus" in result
        assert "default domain" not in result

    def test_override_adds_new_layer(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "00-core.md").write_text("core")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "90-custom.md").write_text("corpus-specific rules")

        result = assemble_prompt(layers_dir=defaults, overrides_dir=overrides)

        assert "core" in result
        assert "corpus-specific rules" in result
        # Custom layer sorts after core by prefix
        assert result.index("core") < result.index("corpus-specific rules")


class TestRoundTrip:
    """Extracted layers must reproduce the original monolithic prompt."""

    def test_assembled_matches_monolith(self):
        """The assembled default layers must match AGENTIC_SEARCH_SYSTEM_PROMPT exactly."""
        from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT

        assembled = assemble_prompt()  # uses default layers_dir

        assert assembled.strip() == AGENTIC_SEARCH_SYSTEM_PROMPT.strip(), (
            "Assembled layers diverged from AGENTIC_SEARCH_SYSTEM_PROMPT. "
            "Diff the two strings to find the discrepancy."
        )
