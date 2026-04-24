"""Pure-Python tests for slugify — no DB required."""
from app.services.technology_service import slugify


def test_slugify_lowercases():
    assert slugify("PostgreSQL") == "postgresql"


def test_slugify_replaces_punctuation_with_dash():
    assert slugify("My Custom Tech!") == "my-custom-tech"


def test_slugify_collapses_multiple_separators():
    assert slugify("A___B   C...D") == "a-b-c-d"


def test_slugify_strips_leading_trailing_dashes():
    assert slugify("---hello---") == "hello"


def test_slugify_handles_mixed_alnum():
    assert slugify("gRPC 2.0") == "grpc-2-0"


def test_slugify_empty_becomes_tech():
    assert slugify("!!!") == "tech"
    assert slugify("") == "tech"


def test_slugify_preserves_dashes_between_alnum():
    assert slugify("aws-s3") == "aws-s3"
