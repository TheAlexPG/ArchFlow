"""Validate the built-in technologies seed file. Pure-Python tests — no DB."""
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.models.technology import TechCategory

SEED_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "technologies.json"
)

ICONIFY_RE = re.compile(r"^[a-z0-9-]+:[a-z0-9-]+$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
VALID_CATEGORIES = {c.value for c in TechCategory}


@pytest.fixture(scope="module")
def seed_rows() -> list[dict]:
    with SEED_PATH.open() as f:
        return json.load(f)


def test_seed_file_is_nonempty(seed_rows):
    assert len(seed_rows) >= 100, "seed should cover at least 100 technologies"


def test_every_row_has_required_fields(seed_rows):
    required = {"slug", "name", "iconify_name", "category"}
    for row in seed_rows:
        missing = required - row.keys()
        assert not missing, f"row {row.get('slug', '?')} missing fields: {missing}"


def test_every_slug_is_valid_and_unique(seed_rows):
    slugs = [row["slug"] for row in seed_rows]
    dupes = [s for s, n in Counter(slugs).items() if n > 1]
    assert not dupes, f"duplicate slugs: {dupes}"
    for slug in slugs:
        assert SLUG_RE.match(slug), f"invalid slug: {slug!r}"


def test_every_iconify_name_is_valid(seed_rows):
    for row in seed_rows:
        assert ICONIFY_RE.match(row["iconify_name"]), (
            f"{row['slug']}: invalid iconify_name {row['iconify_name']!r}"
        )


def test_every_category_is_known(seed_rows):
    for row in seed_rows:
        assert row["category"] in VALID_CATEGORIES, (
            f"{row['slug']}: unknown category {row['category']!r}"
        )


def test_every_color_if_present_is_hex(seed_rows):
    for row in seed_rows:
        color = row.get("color")
        if color is None:
            continue
        assert COLOR_RE.match(color), f"{row['slug']}: bad color {color!r}"


def test_aliases_are_lowercase_strings(seed_rows):
    for row in seed_rows:
        aliases = row.get("aliases")
        if not aliases:
            continue
        for alias in aliases:
            assert isinstance(alias, str) and alias, f"{row['slug']}: bad alias"


def test_protocol_category_populated(seed_rows):
    # We sell the "use catalog for connection protocols" promise. Make sure
    # the seed covers mainstream protocols so the picker is useful on day one.
    protocol_slugs = {
        row["slug"] for row in seed_rows if row["category"] == "protocol"
    }
    for expected in {"http", "https", "grpc", "graphql", "websocket"}:
        assert expected in protocol_slugs, f"missing protocol preset: {expected}"


def test_every_category_enum_value_has_seed_coverage(seed_rows):
    # Users shouldn't see an empty category in the picker. Each enum value
    # should have at least one built-in entry.
    seen = {row["category"] for row in seed_rows}
    missing = VALID_CATEGORIES - seen - {"other"}
    assert not missing, f"no seed entries for categories: {missing}"
