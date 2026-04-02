"""Prompt layer discovery and assembly — layered prompts with override support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_DEFAULT_LAYERS_DIR = Path(__file__).resolve().parent / "prompt_layers"


@dataclass(frozen=True)
class PromptLayer:
    """A single prompt layer file."""

    name: str
    content: str
    path: Path


def discover_layers(layers_dir: Path | None = None) -> list[PromptLayer]:
    """Discover and return prompt layers sorted by filename prefix.

    Files must be .md and non-empty. Sorted lexicographically by name
    (numeric prefixes like 00-, 10-, 20- control order).
    """
    directory = layers_dir or _DEFAULT_LAYERS_DIR
    if not directory.is_dir():
        return []

    layers = []
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        content = path.read_text().strip()
        if not content:
            continue
        layers.append(PromptLayer(name=path.name, content=content, path=path))

    return layers


def load_preamble(
    layers_dir: Path | None = None,
    override_dir: Path | None = None,
) -> str:
    """Load domain preamble from ``_preamble.md``.

    Checks override_dir first, falls back to layers_dir (or built-in default).
    Returns the file content with a trailing ``\\n\\n``, or ``""`` if not found.
    """
    default_dir = layers_dir or _DEFAULT_LAYERS_DIR

    # Override takes precedence
    if override_dir is not None:
        override_path = override_dir / "_preamble.md"
        if override_path.is_file():
            content = override_path.read_text().strip()
            if content:
                return content + "\n\n"

    default_path = default_dir / "_preamble.md"
    if default_path.is_file():
        content = default_path.read_text().strip()
        if content:
            return content + "\n\n"

    return ""


def load_layer_file(
    name: str,
    layers_dir: Path | None = None,
    override_dir: Path | None = None,
) -> str:
    """Load a single named layer file (e.g. ``_voice.md``).

    Checks override_dir first, falls back to layers_dir (or built-in default).
    Returns the file content with a trailing ``\\n\\n``, or ``""`` if not found.
    """
    default_dir = layers_dir or _DEFAULT_LAYERS_DIR

    # Override takes precedence
    if override_dir is not None:
        override_path = override_dir / name
        if override_path.is_file():
            content = override_path.read_text().strip()
            if content:
                return content + "\n\n"

    default_path = default_dir / name
    if default_path.is_file():
        content = default_path.read_text().strip()
        if content:
            return content + "\n\n"

    return ""


def assemble_prompt(
    layers_dir: Path | None = None,
    overrides_dir: Path | None = None,
) -> str:
    """Assemble system prompt from discovered layers.

    Args:
        layers_dir: Directory of default layer files. Uses built-in default if None.
        overrides_dir: Optional override directory. Files here replace default layers
            with the same filename (e.g., ``10-domain.md`` overrides the default
            ``10-domain.md``). New files are added in sort order.

    Returns:
        Concatenated prompt string with double-newline separators.
    """
    layers = discover_layers(layers_dir)

    if overrides_dir is not None:
        override_map = {layer.name: layer for layer in discover_layers(overrides_dir)}
        layers = [override_map.get(layer.name, layer) for layer in layers]
        # Also add any override-only layers (new files not in defaults)
        default_names = {layer.name for layer in layers}
        for override in discover_layers(overrides_dir):
            if override.name not in default_names:
                layers.append(override)
        layers.sort(key=lambda layer: layer.name)

    if not layers:
        return ""

    return "\n\n".join(layer.content for layer in layers)
