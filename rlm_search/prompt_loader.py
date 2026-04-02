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
        content = path.read_text().strip()
        if not content:
            continue
        layers.append(PromptLayer(name=path.name, content=content, path=path))

    return layers


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
