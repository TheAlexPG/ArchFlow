"""Unit tests for export service formatters that don't need a live DB.

Each test stubs out `diagram_service.get_diagram_payload` so we can pin the
shape of the rendered text without spinning up Postgres rows. The service-
level coverage complements the end-to-end API tests, which exercise the
DB-backed path but only against the C4 diagram types.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.connection import ConnectionDirection
from app.models.diagram import DiagramType
from app.models.object import ObjectStatus, ObjectType
from app.services import (
    c4_common,
    mermaid_service,
    plantuml_service,
    structurizr_service,
)


def _obj(name, type_, *, description=None, technology_ids=None, parent_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        type=type_,
        status=ObjectStatus.LIVE,
        description=description,
        technology_ids=technology_ids,
        parent_id=parent_id,
    )


def _placement(obj):
    return SimpleNamespace(
        object_id=obj.id, object=obj, position_x=0.0, position_y=0.0, width=None, height=None
    )


def _conn(src, tgt, label, *, direction=ConnectionDirection.UNIDIRECTIONAL, protocol_ids=None):
    return SimpleNamespace(
        source_id=src.id,
        target_id=tgt.id,
        label=label,
        direction=direction,
        protocol_ids=protocol_ids,
    )


def _diagram(type_=DiagramType.SYSTEM_LANDSCAPE, name="Demo"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        type=type_,
        description=None,
        scope_object_id=None,
    )


def _patch_payload(payload):
    """Patch get_diagram_payload to return `payload` for any caller."""

    async def fake(db, diagram):
        return payload

    return patch("app.services.diagram_service.get_diagram_payload", new=fake)


# ─── c4_common keyword mapping ─────────────────────────────


@pytest.mark.parametrize(
    "obj_type,diagram_type,expected",
    [
        # Landscape / context: STORE collapses to SystemDb, APP/COMPONENT to System
        (ObjectType.STORE, DiagramType.SYSTEM_LANDSCAPE, "SystemDb"),
        (ObjectType.STORE, DiagramType.SYSTEM_CONTEXT, "SystemDb"),
        (ObjectType.APP, DiagramType.SYSTEM_LANDSCAPE, "System"),
        (ObjectType.COMPONENT, DiagramType.SYSTEM_CONTEXT, "System"),
        # Container view: STORE is ContainerDb, APP/COMPONENT both Container
        (ObjectType.STORE, DiagramType.CONTAINER, "ContainerDb"),
        (ObjectType.APP, DiagramType.CONTAINER, "Container"),
        (ObjectType.COMPONENT, DiagramType.CONTAINER, "Container"),
        # Component view: COMPONENT renders as Component
        (ObjectType.COMPONENT, DiagramType.COMPONENT, "Component"),
        (ObjectType.APP, DiagramType.COMPONENT, "Container"),
        (ObjectType.STORE, DiagramType.COMPONENT, "ContainerDb"),
        # Universals
        (ObjectType.ACTOR, DiagramType.CONTAINER, "Person"),
        (ObjectType.SYSTEM, DiagramType.SYSTEM_LANDSCAPE, "System"),
        (ObjectType.EXTERNAL_SYSTEM, DiagramType.CONTAINER, "System_Ext"),
        (ObjectType.GROUP, DiagramType.SYSTEM_LANDSCAPE, "System_Boundary"),
    ],
)
def test_c4_keyword_is_diagram_type_aware(obj_type, diagram_type, expected):
    assert c4_common.c4_keyword(obj_type, diagram_type) == expected


# ─── Mermaid C4 ─────────────────────────────────────────────


async def test_mermaid_landscape_uses_systemdb_not_containerdb():
    """STORE on a landscape diagram must NOT emit ContainerDb (codex H2)."""
    db = _obj("Postgres", ObjectType.STORE)
    payload = {
        "placements": [_placement(db)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.SYSTEM_LANDSCAPE)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    assert "C4Context" in text
    assert 'SystemDb(' in text
    assert "ContainerDb(" not in text


async def test_mermaid_container_keeps_containerdb():
    db_obj = _obj("Postgres", ObjectType.STORE)
    payload = {
        "placements": [_placement(db_obj)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CONTAINER)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    assert "C4Container" in text
    assert "ContainerDb(" in text


async def test_mermaid_group_emits_boundary_block_with_children():
    """ObjectType.GROUP must render as a System_Boundary { ... } block (codex H4)."""
    boundary = _obj("Backend", ObjectType.GROUP)
    api = _obj("API", ObjectType.APP, parent_id=boundary.id)
    payload = {
        "placements": [_placement(boundary), _placement(api)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CONTAINER)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    # Boundary opens with `{` and closes with `}`
    assert 'System_Boundary(' in text
    assert text.count("{") >= 1 and text.count("}") >= 1
    # The child Container line is indented further than the boundary line
    boundary_line = next(line for line in text.splitlines() if "System_Boundary(" in line)
    child_line = next(line for line in text.splitlines() if "Container(" in line)
    assert (len(child_line) - len(child_line.lstrip())) > (
        len(boundary_line) - len(boundary_line.lstrip())
    )


async def test_mermaid_c4_birel_for_bidirectional():
    user = _obj("User", ObjectType.ACTOR)
    api = _obj("API", ObjectType.SYSTEM, description="Backend")
    payload = {
        "placements": [_placement(user), _placement(api)],
        "connections": [
            _conn(user, api, "talks", direction=ConnectionDirection.BIDIRECTIONAL)
        ],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.SYSTEM_LANDSCAPE)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    assert "C4Context" in text
    assert "BiRel(" in text


# ─── Mermaid flowchart round-trip ───────────────────────────


async def test_mermaid_flowchart_round_trips_through_parser():
    """Custom-diagram flowchart export must parse via mermaid_service.parse() (codex M1)."""
    user = _obj("User", ObjectType.ACTOR)
    api = _obj("API", ObjectType.SYSTEM)
    db_obj = _obj("DB", ObjectType.STORE)
    payload = {
        "placements": [_placement(user), _placement(api), _placement(db_obj)],
        "connections": [
            _conn(user, api, "logs in"),
            _conn(api, db_obj, "reads"),
        ],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CUSTOM)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    objs, rels = mermaid_service.parse(text)
    assert len(objs) == 3
    assert len(rels) == 2
    assert {o["name"] for o in objs} == {"User", "API", "DB"}
    expected_rels = {("n_", "logs in"), ("n_", "reads")}
    assert {(r["source_alias"][:2], r["label"]) for r in rels} == expected_rels


# ─── PlantUML ───────────────────────────────────────────────


async def test_plantuml_landscape_uses_systemdb():
    db_obj = _obj("Postgres", ObjectType.STORE)
    payload = {
        "placements": [_placement(db_obj)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.SYSTEM_LANDSCAPE)

    with _patch_payload(payload):
        text = await plantuml_service.export_plantuml(db=None, diagram=diagram)

    assert "C4_Context.puml" in text
    assert "SystemDb(" in text
    assert "ContainerDb(" not in text


async def test_plantuml_group_emits_boundary_block():
    boundary = _obj("Backend", ObjectType.GROUP)
    api = _obj("API", ObjectType.APP, parent_id=boundary.id)
    payload = {
        "placements": [_placement(boundary), _placement(api)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CONTAINER)

    with _patch_payload(payload):
        text = await plantuml_service.export_plantuml(db=None, diagram=diagram)

    assert "System_Boundary(" in text
    # Child Container lives inside braces
    container_idx = text.index("Container(")
    open_brace_idx = text.index("{")
    close_brace_idx = text.rindex("}")
    assert open_brace_idx < container_idx < close_brace_idx


async def test_plantuml_includes_tech_label():
    user = _obj("User", ObjectType.ACTOR)
    api = _obj(
        "API",
        ObjectType.APP,
        description="Backend",
        technology_ids=[uuid.uuid4()],
    )
    tech_id = api.technology_ids[0]
    payload = {
        "placements": [_placement(user), _placement(api)],
        "connections": [_conn(user, api, "uses")],
        "tech_names": {tech_id: "FastAPI"},
    }
    diagram = _diagram(DiagramType.CONTAINER)

    with _patch_payload(payload):
        text = await plantuml_service.export_plantuml(db=None, diagram=diagram)

    assert text.startswith("@startuml")
    assert text.rstrip().endswith("@enduml")
    assert '"FastAPI"' in text
    assert 'Container(' in text


# ─── Structurizr round-trip ────────────────────────────────


async def test_structurizr_nested_blocks_round_trip():
    """Parent objects with placed children render as nested DSL blocks
    that re-parse through import_dsl (codex H3)."""
    parent = _obj("Backend", ObjectType.SYSTEM, description="System")
    child = _obj("API", ObjectType.APP, parent_id=parent.id)
    payload = {
        "placements": [_placement(parent), _placement(child)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CONTAINER)

    with _patch_payload(payload):
        text = await structurizr_service.export_dsl(db=None, diagram=diagram)

    # Nested form, not the broken inline `# parent:` comment
    assert "# parent:" not in text
    assert "{" in text and "}" in text

    # Re-parse: importer recovers parent_alias on the child
    parsed_objs, parsed_rels = structurizr_service.parse(text)
    by_name = {o["name"]: o for o in parsed_objs}
    assert "Backend" in by_name and "API" in by_name
    api = by_name["API"]
    backend = by_name["Backend"]
    assert api["parent_alias"] == backend["alias"]


async def test_structurizr_group_emits_block_with_alias():
    grp = _obj("Backend", ObjectType.GROUP)
    api = _obj("API", ObjectType.APP, parent_id=grp.id)
    payload = {
        "placements": [_placement(grp), _placement(api)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CONTAINER)

    with _patch_payload(payload):
        text = await structurizr_service.export_dsl(db=None, diagram=diagram)

    assert " group " in text
    parsed_objs, _ = structurizr_service.parse(text)
    by_type = {o["name"]: o["type"] for o in parsed_objs}
    assert by_type["Backend"] == ObjectType.GROUP
    assert by_type["API"] == ObjectType.APP


# ─── Escaping ──────────────────────────────────────────────


async def test_mermaid_c4_escapes_quotes_in_names():
    obj = _obj('System "Prod"', ObjectType.SYSTEM, description='Has "quotes"')
    payload = {
        "placements": [_placement(obj)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.SYSTEM_LANDSCAPE)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    # Original double-quotes get swapped for apostrophes — no embedded `"` inside macro args
    assert 'System(n_' in text
    # Each macro line should have an even number of double-quote chars (start+end of args)
    for line in text.splitlines():
        if line.strip().startswith("System("):
            assert line.count('"') % 2 == 0


async def test_mermaid_flowchart_escapes_pipe_and_bracket_in_labels():
    user = _obj("User|Admin", ObjectType.ACTOR)
    api = _obj("API[v1]", ObjectType.SYSTEM)
    payload = {
        "placements": [_placement(user), _placement(api)],
        "connections": [_conn(user, api, "uses|HTTPS")],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.CUSTOM)

    with _patch_payload(payload):
        text = await mermaid_service.export_mermaid(db=None, diagram=diagram)

    # `|` inside node labels and edge labels would terminate the syntax
    # — the escape helper swaps it for `/`.
    for line in text.splitlines():
        if line.strip().startswith("n_") and ("[" in line):
            # Node lines: bracket pairs must balance
            assert line.count("[") == line.count("]")
        if "-->|" in line:
            # Edge labels: exactly two pipes (open + close) per edge label
            assert line.count("|") == 2


async def test_structurizr_dsl_swaps_quotes_and_backslashes():
    obj = _obj(r'Foo "bar" \\baz', ObjectType.SYSTEM)
    payload = {
        "placements": [_placement(obj)],
        "connections": [],
        "tech_names": {},
    }
    diagram = _diagram(DiagramType.SYSTEM_LANDSCAPE)

    with _patch_payload(payload):
        text = await structurizr_service.export_dsl(db=None, diagram=diagram)

    # The DSL string must not contain raw backslashes or unescaped inner quotes
    parsed_objs, _ = structurizr_service.parse(text)
    assert len(parsed_objs) == 1
    assert "\\" not in parsed_objs[0]["name"]
    # Parser strips outer quotes; inner quote must have been swapped to `'`
    assert '"' not in parsed_objs[0]["name"]
