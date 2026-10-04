"""Consistency checks for the translation files."""

import json
import re
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "powerclimate"
TRANSLATIONS = COMPONENT / "translations"


def _load(language: str) -> dict:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def _key_paths(data, prefix=()) -> set[tuple[str, ...]]:
    if not isinstance(data, dict):
        return {prefix}
    paths: set[tuple[str, ...]] = set()
    for key, value in data.items():
        paths |= _key_paths(value, (*prefix, key))
    return paths


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"{(\w+)}", text))


def _leaf(data: dict, path: tuple[str, ...]) -> str:
    for key in path:
        data = data[key]
    return data


def test_translations_have_the_same_keys_as_english():
    english = _load("en")
    for path in TRANSLATIONS.glob("*.json"):
        other = _load(path.stem)
        assert _key_paths(other) == _key_paths(english), path.name


def test_translations_keep_placeholders():
    english = _load("en")
    for path in TRANSLATIONS.glob("*.json"):
        other = _load(path.stem)
        for key_path in _key_paths(english):
            assert _placeholders(_leaf(other, key_path)) == _placeholders(
                _leaf(english, key_path)
            ), (path.name, key_path)


def test_entity_translation_keys_exist():
    entity = _load("en")["entity"]
    for platform in ("sensor", "climate"):
        source = (COMPONENT / f"{platform}.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'translation_key(?: =|=) ?"(\w+)"', source))
        assert keys, platform
        for key in keys:
            assert key in entity[platform], f"{platform}.{key}"
