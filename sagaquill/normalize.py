from __future__ import annotations

from typing import Any

from .models import CharacterSeed


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def best_text(*values: Any) -> str:
    for value in values:
        cleaned = text(value)
        if cleaned:
            return cleaned
    return ""


def optional_text(value: Any) -> str | None:
    cleaned = text(value)
    return cleaned or None


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        cleaned = text(item)
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items


def character_seed_list(value: Any, *, allow_strings: bool = True) -> list[CharacterSeed]:
    if not isinstance(value, list):
        return []
    seeds: list[CharacterSeed] = []
    for item in value:
        if allow_strings and isinstance(item, str):
            name = text(item)
            if name:
                seeds.append(CharacterSeed(name=name))
            continue
        if not isinstance(item, dict):
            continue
        name = best_text(item.get("name"), "")
        if not name:
            continue
        seeds.append(
            CharacterSeed(
                name=name,
                role=best_text(item.get("role"), ""),
                goal=best_text(item.get("goal"), ""),
                conflict=best_text(item.get("conflict"), ""),
                notes=best_text(item.get("notes"), ""),
            )
        )
    return seeds
