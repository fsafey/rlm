"""Tests for prompt layer discovery and assembly."""

from __future__ import annotations

from pathlib import Path

from rlm_search.prompt_loader import (
    assemble_prompt,
    discover_layers,
    load_layer_file,
    load_preamble,
)


class TestDiscoverLayers:
    """Layer discovery from a directory of numbered markdown files."""

    def test_discovers_and_orders_by_prefix(self, tmp_path: Path):
        (tmp_path / "20-tools.md").write_text("## Tools\nresearch() docs")
        (tmp_path / "00-core.md").write_text("## Core\nREPL rules")
        (tmp_path / "10-domain.md").write_text("## Domain\nI.M.A.M. preamble")

        layers = discover_layers(tmp_path)

        assert [layer.name for layer in layers] == ["00-core.md", "10-domain.md", "20-tools.md"]
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

    def test_skips_underscore_prefixed_files(self, tmp_path: Path):
        (tmp_path / "00-core.md").write_text("core content")
        (tmp_path / "_preamble.md").write_text("preamble metadata")

        layers = discover_layers(tmp_path)
        assert len(layers) == 1
        assert layers[0].name == "00-core.md"


class TestLoadPreamble:
    """Load domain preamble from _preamble.md, with override support."""

    def test_reads_from_default_dir(self, tmp_path: Path):
        (tmp_path / "_preamble.md").write_text("Sources are from TestCorpus.\n")

        result = load_preamble(layers_dir=tmp_path)
        assert result == "Sources are from TestCorpus.\n\n"

    def test_override_dir_takes_precedence(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "_preamble.md").write_text("Default preamble.")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "_preamble.md").write_text("Custom preamble for medical corpus.")

        result = load_preamble(layers_dir=defaults, override_dir=overrides)
        assert "medical corpus" in result
        assert "Default" not in result

    def test_falls_back_to_default_when_no_override(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "_preamble.md").write_text("Default preamble.")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        # No _preamble.md in overrides

        result = load_preamble(layers_dir=defaults, override_dir=overrides)
        assert "Default preamble" in result

    def test_returns_empty_when_no_file(self, tmp_path: Path):
        result = load_preamble(layers_dir=tmp_path)
        assert result == ""


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
        """Assembled layers + placeholder injection must match AGENTIC_SEARCH_SYSTEM_PROMPT."""
        from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT
        from rlm_search.tool_gate import generate_availability_section

        assembled = assemble_prompt()  # uses default layers_dir
        # Apply same placeholder replacement as prompts.py
        assembled = assembled.replace("{TOOL_GATE_SECTION}", generate_availability_section())

        assert assembled.strip() == AGENTIC_SEARCH_SYSTEM_PROMPT.strip(), (
            "Assembled layers diverged from AGENTIC_SEARCH_SYSTEM_PROMPT. "
            "Diff the two strings to find the discrepancy."
        )


class TestLoadLayerFile:
    """Load a single named layer file with override support."""

    def test_reads_from_default_dir(self, tmp_path: Path):
        (tmp_path / "_voice.md").write_text("VOICE & TONE:\n- Be declarative.")

        result = load_layer_file("_voice.md", layers_dir=tmp_path)
        assert result == "VOICE & TONE:\n- Be declarative.\n\n"

    def test_override_dir_takes_precedence(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "_voice.md").write_text("Default voice.")

        overrides = tmp_path / "overrides"
        overrides.mkdir()
        (overrides / "_voice.md").write_text("Custom voice for medical corpus.")

        result = load_layer_file("_voice.md", layers_dir=defaults, override_dir=overrides)
        assert "medical corpus" in result
        assert "Default" not in result

    def test_falls_back_to_default_when_no_override(self, tmp_path: Path):
        defaults = tmp_path / "defaults"
        defaults.mkdir()
        (defaults / "_voice.md").write_text("Default voice.")

        overrides = tmp_path / "overrides"
        overrides.mkdir()

        result = load_layer_file("_voice.md", layers_dir=defaults, override_dir=overrides)
        assert "Default voice" in result

    def test_returns_empty_when_no_file(self, tmp_path: Path):
        result = load_layer_file("_voice.md", layers_dir=tmp_path)
        assert result == ""

    def test_skips_empty_file(self, tmp_path: Path):
        (tmp_path / "_voice.md").write_text("   \n  ")
        result = load_layer_file("_voice.md", layers_dir=tmp_path)
        assert result == ""


class TestBuiltInLayerFiles:
    """Built-in _voice.md and _answer_format.md load correctly."""

    def test_voice_loads(self):
        result = load_layer_file("_voice.md")
        assert "VOICE & TONE" in result
        assert "I.M.A.M." in result

    def test_answer_format_loads(self):
        result = load_layer_file("_answer_format.md")
        assert "## Answer" in result
        assert "## Sources Consulted" in result
        assert "## Confidence Assessment" in result

    def test_cached_exports_match_direct_load(self):
        from rlm_search.prompts import ANSWER_FORMAT, VOICE

        assert VOICE == load_layer_file("_voice.md")
        assert ANSWER_FORMAT == load_layer_file("_answer_format.md")

    def test_prompt_layers_dir_override(self, tmp_path: Path):
        (tmp_path / "_voice.md").write_text("Custom voice for testing.")
        result = load_layer_file("_voice.md", override_dir=tmp_path)
        assert "Custom voice for testing" in result


class TestBuildSystemPromptLayers:
    """build_system_prompt() uses cached AGENTIC_SEARCH_SYSTEM_PROMPT."""

    def test_build_includes_budget_and_base(self):
        from rlm_search.prompts import AGENTIC_SEARCH_SYSTEM_PROMPT, build_system_prompt

        prompt = build_system_prompt(max_iterations=10)

        assert prompt.startswith(AGENTIC_SEARCH_SYSTEM_PROMPT)
        assert "10 iterations" in prompt
