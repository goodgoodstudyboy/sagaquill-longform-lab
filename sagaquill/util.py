from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def ensure_directory(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: to_plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    return value


def dump_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    ensure_directory(target.parent)
    target.write_text(
        json.dumps(to_plain_data(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def dump_text(path: str | Path, content: str) -> None:
    target = Path(path)
    ensure_directory(target.parent)
    target.write_text(content, encoding="utf-8")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compact_json(payload: Any) -> str:
    return json.dumps(to_plain_data(payload), ensure_ascii=False, indent=2)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    if normalized:
        cleaned = re.sub(r"[^a-zA-Z0-9-]+", "-", normalized).strip("-").lower()
    else:
        cleaned = re.sub(r"[^\w-]+", "-", value.strip(), flags=re.UNICODE).strip("-").lower()
    return cleaned or "novel"


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_json_object(text: str) -> Any:
    candidate = strip_markdown_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char not in "{[":
            continue
        try:
            payload, end = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        return payload
    raise ValueError("Could not parse JSON payload from model output.")


def non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
