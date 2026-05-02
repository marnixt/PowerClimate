"""Tests for PowerClimate helper utilities."""

from pathlib import Path
from types import SimpleNamespace

from custom_components.powerclimate import helpers


def make_hass(base_path: Path, language: str) -> SimpleNamespace:
    """Create a minimal Home Assistant config stub for string loading tests."""

    class Config:
        def __init__(self, root: Path, lang: str) -> None:
            self.language = lang
            self._root = root

        def path(self, *parts: str) -> str:
            return str(self._root.joinpath(*parts))

    return SimpleNamespace(config=Config(base_path, language))


def test_get_strings_uses_language_specific_override(tmp_path) -> None:
    """Language-specific custom strings should override the default file when present."""
    strings_dir = tmp_path / "custom_components" / "powerclimate"
    strings_dir.mkdir(parents=True)
    (strings_dir / "custom_strings.json").write_text('{"greeting":"hello"}', encoding="utf-8")
    (strings_dir / "custom_strings.nl.json").write_text('{"greeting":"hallo"}', encoding="utf-8")

    helpers._STRING_CACHE.clear()
    result = helpers.get_strings(make_hass(tmp_path, "nl-NL"))

    assert result["greeting"] == "hallo"


def test_get_strings_falls_back_to_default_file(tmp_path) -> None:
    """Missing language overrides should fall back to the shared custom strings file."""
    strings_dir = tmp_path / "custom_components" / "powerclimate"
    strings_dir.mkdir(parents=True)
    (strings_dir / "custom_strings.json").write_text('{"greeting":"hello"}', encoding="utf-8")

    helpers._STRING_CACHE.clear()
    result = helpers.get_strings(make_hass(tmp_path, "fr-FR"))

    assert result["greeting"] == "hello"
