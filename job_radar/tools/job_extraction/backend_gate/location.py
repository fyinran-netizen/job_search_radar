"""Data-driven location normalization used by extraction and Basic Gate."""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pypinyin import lazy_pinyin

CHINA_CITIES_PATH = Path(__file__).with_name("data") / "china_cities.json"
_SEPARATORS = re.compile(r"\s*(?:[,，;；/\\|])\s*")
_NOISE = re.compile(
    r"(?:\s*[\(（\[]\s*(?:总部|分部|办事处|办公室|hq|headquarters|office|branch)"
    r"\s*[\)）\]]|\s*[-,:：，]?\s*(?:总部|分部|办事处|办公室|hq|headquarters|office|branch))\s*$",
    re.I,
)


@dataclass(frozen=True)
class CityEntry:
    city: str
    province: str | None = None
    aliases: tuple[str, ...] = ()


def load_city_catalog(path: Path | None = None) -> list[CityEntry]:
    return list(_load_city_catalog_cached(str(path or CHINA_CITIES_PATH)))


@lru_cache(maxsize=None)
def _load_city_catalog_cached(path: str) -> tuple[CityEntry, ...]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ()
    return tuple(_parse_catalog(payload))


def normalize_locations(values: list[str], *, catalog: list[CityEntry] | None = None) -> list[str]:
    """Normalize locations, preferring city matches over their province."""
    entries = catalog if catalog is not None else load_city_catalog()
    candidates = [
        cleaned
        for value in values
        for part in _SEPARATORS.split(_clean(value))
        if (cleaned := _clean_location(part))
    ]
    city_matches = [_match_city(candidate, entries) for candidate in candidates]
    matched_provinces = {
        _location_key(entry.province)
        for entry in city_matches
        if entry and entry.province
    }
    result: list[str] = []
    for candidate, city_entry in zip(candidates, city_matches):
        if city_entry:
            display = city_entry.city
        else:
            province = _match_province(candidate, entries)
            display = None if province and _location_key(province) in matched_provinces else (province or candidate)
        if display and display not in result:
            result.append(display)
    return result


def normalize_location(value: str | None, *, catalog: list[CityEntry] | None = None) -> str:
    return ", ".join(normalize_locations([value] if value else [], catalog=catalog))


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_location(value: str) -> str:
    return _strip_suffix(_NOISE.sub("", value).strip())


def _strip_suffix(value: str) -> str:
    return re.sub(r"(?:市|city|省|province)$", "", value, flags=re.I).strip()


def _location_key(value: str | None) -> str:
    value = _strip_suffix(value or "")
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in value if not char.isspace() and not unicodedata.category(char).startswith("P"))


def _match_city(candidate: str, entries: list[CityEntry]) -> CityEntry | None:
    key = _location_key(candidate)
    for entry in entries:
        if entry.city and key in {_location_key(entry.city), *(_location_key(alias) for alias in entry.aliases)}:
            return entry
    return None


def _match_province(candidate: str, entries: list[CityEntry]) -> str | None:
    key = _location_key(candidate)
    for entry in entries:
        if entry.city:
            continue
        names = (entry.province, *entry.aliases)
        if any(key == _location_key(name) for name in names if name):
            return entry.province
    return None


def _parse_catalog(payload: Any) -> list[CityEntry]:
    rows = payload.get("cities", payload.get("data", [])) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    result: list[CityEntry] = []
    for row in rows:
        if isinstance(row, str):
            result.append(_direct_entry(row))
            continue
        if not isinstance(row, dict):
            continue
        raw_name = row.get("city") or row.get("name")
        if not raw_name:
            continue
        name = str(raw_name).strip()
        province_name = _display_province(name)
        children = row.get("children")
        # Autonomous and special administrative regions stay province-level.
        if isinstance(children, list) and not _is_province_level_region(name):
            result.append(CityEntry("", province_name, _aliases(name, row)))
            for child in children:
                if isinstance(child, dict) and child.get("name"):
                    child_name = _strip_suffix(str(child["name"]).strip())
                    result.append(CityEntry(child_name, province_name, _aliases(child_name, child)))
        elif _is_city_name(name):
            city = _strip_suffix(name)
            result.append(CityEntry(city, None, _aliases(city, row)))
        else:
            result.append(CityEntry("", province_name, _aliases(name, row)))
    return result


def _aliases(name: str, row: dict[str, Any]) -> tuple[str, ...]:
    aliases = row.get("aliases", row.get("alias", []))
    if isinstance(aliases, str):
        aliases = [aliases]
    values = list(aliases) if isinstance(aliases, list) else []
    values.extend(row[key] for key in ("pinyin", "english", "en") if row.get(key))
    values.append("".join(lazy_pinyin(_strip_suffix(name), errors="keep")))
    return tuple(str(value).strip() for value in values if str(value).strip())


def _direct_entry(name: str) -> CityEntry:
    if _is_city_name(name):
        city = _strip_suffix(name)
        return CityEntry(city, None, _aliases(city, {}))
    province = _display_province(name)
    return CityEntry("", province, _aliases(name, {}))


def _display_province(name: str) -> str:
    return re.sub(r"(?:省|province)$", "", name.strip(), flags=re.I).strip()


def _is_city_name(name: str) -> bool:
    return name.strip().lower().endswith(("市", "city"))


def _is_province_level_region(name: str) -> bool:
    return name.strip().endswith(("自治区", "特别行政区"))
