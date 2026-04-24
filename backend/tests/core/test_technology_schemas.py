"""Pydantic schema validation for TechnologyCreate / TechnologyUpdate."""
import pytest
from pydantic import ValidationError

from app.models.technology import TechCategory
from app.schemas.technology import TechnologyCreate, TechnologyUpdate


def _base_payload(**overrides):
    data = {
        "name": "Custom Tech",
        "slug": "custom-tech",
        "iconify_name": "logos:python",
        "category": TechCategory.TOOL,
    }
    data.update(overrides)
    return data


class TestTechnologyCreate:
    def test_minimal_valid(self):
        t = TechnologyCreate(
            name="Figma",
            iconify_name="logos:figma",
            category=TechCategory.SAAS,
        )
        assert t.name == "Figma"
        assert t.slug is None  # service will auto-generate

    def test_valid_slug_variations(self):
        for slug in ["a", "go", "my-tech", "nextjs", "aws-s3", "kube2"]:
            TechnologyCreate(**_base_payload(slug=slug))

    @pytest.mark.parametrize(
        "slug",
        [
            "",
            "-bad",
            "bad-",
            "Bad",
            "has_underscore",
            "has space",
            "has.dot",
            "x" * 65,
        ],
    )
    def test_invalid_slug_rejected(self, slug):
        with pytest.raises(ValidationError):
            TechnologyCreate(**_base_payload(slug=slug))

    @pytest.mark.parametrize(
        "iconify_name",
        [
            "logos:python",
            "simple-icons:figma",
            "mdi:web",
            "logos:aws-s3",
        ],
    )
    def test_valid_iconify_names(self, iconify_name):
        TechnologyCreate(**_base_payload(iconify_name=iconify_name))

    @pytest.mark.parametrize(
        "iconify_name",
        [
            "noprefix",
            "logos:",
            ":name",
            "Logos:Python",
            "logos:python:extra",
            "logos:py thon",
        ],
    )
    def test_invalid_iconify_names_rejected(self, iconify_name):
        with pytest.raises(ValidationError):
            TechnologyCreate(**_base_payload(iconify_name=iconify_name))

    @pytest.mark.parametrize("color", ["#336791", "#FF0000", "#00ADD8", "#000000FF"])
    def test_valid_colors(self, color):
        TechnologyCreate(**_base_payload(color=color))

    @pytest.mark.parametrize("color", ["336791", "#ZZZZZZ", "#12", "#12345", "red"])
    def test_invalid_colors_rejected(self, color):
        with pytest.raises(ValidationError):
            TechnologyCreate(**_base_payload(color=color))


class TestTechnologyUpdate:
    def test_all_fields_optional(self):
        u = TechnologyUpdate()
        assert u.name is None
        assert u.iconify_name is None

    def test_partial_update_valid(self):
        u = TechnologyUpdate(name="Renamed", category=TechCategory.CLOUD)
        assert u.name == "Renamed"
        assert u.category is TechCategory.CLOUD

    def test_invalid_iconify_still_rejected_on_update(self):
        with pytest.raises(ValidationError):
            TechnologyUpdate(iconify_name="invalid_name")
