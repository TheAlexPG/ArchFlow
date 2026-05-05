"""Structurizr DSL bridge — importer + exporter.

Importer: parses the subset of DSL that maps cleanly onto ArchFlow's model.
Exporter: emits the same subset, so an exported diagram round-trips through
`POST /import/structurizr` back into equivalent objects + connections.

Importer-supported subset:

    workspace {
      model {
        u = person "User"
        s = softwareSystem "Name" "Description" {
          c = container "Web" "Docs" "React"
          d = container "DB" "Stores data" "Postgres"
        }
        u -> s "Uses"
        c -> d "Reads/writes"
      }
    }

Group blocks, styles, views, and implied relationships are ignored.
"""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection, ConnectionDirection
from app.models.diagram import Diagram
from app.models.object import ModelObject, ObjectType

_KEYWORD_TO_TYPE: dict[str, ObjectType] = {
    "person": ObjectType.ACTOR,
    "softwaresystem": ObjectType.SYSTEM,
    "container": ObjectType.APP,
    "component": ObjectType.COMPONENT,
    "group": ObjectType.GROUP,
}

# matches: ident = keyword "Name" ["Description" ["Technology"]] [{]
_DECL = re.compile(
    r'^\s*(?P<id>[A-Za-z_][\w]*)\s*=\s*'
    r'(?P<kw>person|softwareSystem|container|component|group)\b'
    r'(?:\s+"(?P<name>[^"]*)")?'
    r'(?:\s+"(?P<desc>[^"]*)")?'
    r'(?:\s+"(?P<tech>[^"]*)")?'
    r'(?P<brace>\s*\{)?\s*$',
    re.IGNORECASE,
)

# matches: ident -> ident "Label"
_REL = re.compile(
    r'^\s*(?P<src>[A-Za-z_][\w]*)\s*->\s*(?P<tgt>[A-Za-z_][\w]*)'
    r'(?:\s+"(?P<label>[^"]*)")?'
    r'(?:\s+"(?P<tech>[^"]*)")?\s*$',
)


class StructurizrParseError(ValueError):
    pass


def parse(dsl: str) -> tuple[list[dict], list[dict]]:
    """Return (objects, relationships) as dicts. Nesting is tracked via the
    parent stack so nested `container` blocks get `parent_id` set correctly."""
    objects: list[dict] = []
    relationships: list[dict] = []
    parent_stack: list[str | None] = [None]

    for raw_line in dsl.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Close nested block
        if line == "}":
            if len(parent_stack) > 1:
                parent_stack.pop()
            continue
        # Skip open-only lines like `workspace {` / `model {`
        if re.match(r'^\s*(workspace|model|views|styles)\s*\{?\s*$', line, re.IGNORECASE):
            continue

        # Object declaration
        m = _DECL.match(line)
        if m:
            kw = m.group("kw").lower()
            obj_type = _KEYWORD_TO_TYPE[kw]
            name = m.group("name") or m.group("id")
            description = m.group("desc")
            tech = m.group("tech")
            obj = {
                "alias": m.group("id"),
                "name": name,
                "type": obj_type,
                "description": description,
                "technology": [tech] if tech else None,
                "parent_alias": parent_stack[-1],
            }
            objects.append(obj)
            # Enter nested scope if this decl opened a brace.
            if m.group("brace"):
                parent_stack.append(m.group("id"))
            continue

        # Relationship
        m = _REL.match(line)
        if m:
            relationships.append(
                {
                    "source_alias": m.group("src"),
                    "target_alias": m.group("tgt"),
                    "label": m.group("label"),
                    "technology": m.group("tech"),
                }
            )
            continue

        # Unknown line that opens a block (e.g. bare `container "x" { ... }`
        # without an alias) — just push None so we close correctly.
        if line.endswith("{"):
            parent_stack.append(None)

    return objects, relationships


async def import_dsl(db: AsyncSession, dsl: str) -> dict:
    """Parse a Structurizr DSL blob and materialize ModelObjects + Connections.

    Returns a summary dict with counts and the mapping of DSL aliases to
    created UUIDs. Does not commit — the caller's session manages tx.
    """
    parsed_objects, parsed_rels = parse(dsl)
    alias_to_id: dict[str, uuid.UUID] = {}

    for obj in parsed_objects:
        model_obj = ModelObject(
            name=obj["name"],
            type=obj["type"],
            description=obj["description"],
            # TODO(tech-catalog): resolve obj["technology"] text against the
            # catalog once importers know their target workspace.
        )
        db.add(model_obj)
        await db.flush()
        alias_to_id[obj["alias"]] = model_obj.id

    # Second pass: wire parent_ids now that every alias has an UUID.
    for obj in parsed_objects:
        parent_alias = obj["parent_alias"]
        if parent_alias and parent_alias in alias_to_id:
            my_id = alias_to_id[obj["alias"]]
            result = await db.get(ModelObject, my_id)
            if result is not None:
                result.parent_id = alias_to_id[parent_alias]

    for rel in parsed_rels:
        src = alias_to_id.get(rel["source_alias"])
        tgt = alias_to_id.get(rel["target_alias"])
        if not src or not tgt:
            continue  # relationship references something we didn't import
        conn = Connection(
            source_id=src,
            target_id=tgt,
            label=rel["label"],
            # TODO(tech-catalog): resolve rel["technology"] text against the
            # catalog once importers know their target workspace.
            protocol_ids=None,
        )
        db.add(conn)

    await db.flush()
    return {
        "objects_created": len(alias_to_id),
        "connections_created": len(
            [r for r in parsed_rels if r["source_alias"] in alias_to_id and r["target_alias"] in alias_to_id]
        ),
        "alias_map": {k: str(v) for k, v in alias_to_id.items()},
    }


# ── Exporter ────────────────────────────────────────────


_OBJ_KEYWORD = {
    ObjectType.ACTOR: "person",
    ObjectType.SYSTEM: "softwareSystem",
    ObjectType.EXTERNAL_SYSTEM: "softwareSystem",
    ObjectType.APP: "container",
    ObjectType.STORE: "container",
    ObjectType.COMPONENT: "component",
    ObjectType.GROUP: "group",
}


def _alias(obj_id: uuid.UUID) -> str:
    return f"n_{obj_id.hex[:8]}"


def _esc_dsl(s: str | None) -> str:
    """Sanitize a DSL double-quoted string.

    Structurizr DSL has no `\\"` escape, so we swap quotes for apostrophes,
    drop newlines, and replace backslashes (which the lexer treats specially
    in some implementations) with forward slashes.
    """
    if not s:
        return ""
    return (
        s.replace("\\", "/")
        .replace('"', "'")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def _tech_label(ids, tech_names: dict[uuid.UUID, str]) -> str | None:
    if not ids:
        return None
    names = [tech_names[i] for i in ids if i in tech_names]
    return ", ".join(names) if names else None


def _build_dsl_args(name: str, desc: str, tech: str | None) -> str:
    """Positional DSL string args, padding earlier slots with `""` as needed."""
    parts = [f'"{name}"']
    if tech:
        parts.append(f'"{desc}"')
        parts.append(f'"{tech}"')
    elif desc:
        parts.append(f'"{desc}"')
    return " ".join(parts)


async def export_dsl(db: AsyncSession, diagram: Diagram) -> str:
    """Render `diagram` as Structurizr DSL.

    Parents-with-children get emitted as nested brace blocks so the importer
    in this same file rebuilds the parent_id chain on round-trip — the
    earlier inline `# parent: ...` trick collided with the importer's
    line-anchored declaration regex.

    Note: the `alias = group "..."` form we emit for `ObjectType.GROUP` is
    an ArchFlow extension. Vanilla Structurizr DSL uses bare
    `group "..." { ... }` (no alias), but our importer needs the alias to
    materialize the GROUP as a real ModelObject on round-trip.
    """
    from app.services import diagram_service

    payload = await diagram_service.get_diagram_payload(db, diagram)
    placements = payload["placements"]
    connections = payload["connections"]
    tech_names = payload["tech_names"]

    placed_ids = {p.object_id for p in placements}
    children_by_parent: dict = {}
    top_level: list = []
    for p in placements:
        parent_id = p.object.parent_id
        if parent_id and parent_id in placed_ids:
            children_by_parent.setdefault(parent_id, []).append(p)
        else:
            top_level.append(p)

    lines: list[str] = []
    lines.append("# Exported from ArchFlow")
    lines.append(f"# diagram_id: {diagram.id}")
    lines.append(f"# diagram_type: {diagram.type.value}")
    lines.append(
        f"# objects: {len(placements)}; connections: {len(connections)}"
    )
    lines.append(f'workspace "{_esc_dsl(diagram.name)}" {{')
    lines.append("  model {")

    for p in top_level:
        _emit_dsl_obj(p, children_by_parent, tech_names, lines, indent=4)

    for c in connections:
        src = _alias(c.source_id)
        tgt = _alias(c.target_id)
        label = _esc_dsl(c.label)
        tech = _tech_label(c.protocol_ids, tech_names)
        tech_arg = _esc_dsl(tech) if tech else None
        if tech_arg:
            lines.append(f'    {src} -> {tgt} "{label}" "{tech_arg}"')
        else:
            lines.append(f'    {src} -> {tgt} "{label}"')
        if c.direction == ConnectionDirection.BIDIRECTIONAL:
            # DSL has no native bi-directional arrow; emit the reverse so
            # round-trip preserves the symmetry.
            if tech_arg:
                lines.append(f'    {tgt} -> {src} "{label}" "{tech_arg}"')
            else:
                lines.append(f'    {tgt} -> {src} "{label}"')

    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _emit_dsl_obj(
    placement,
    children_by_parent: dict,
    tech_names: dict,
    lines: list[str],
    indent: int,
) -> None:
    obj = placement.object
    pad = " " * indent
    a = _alias(obj.id)
    kw = _OBJ_KEYWORD.get(obj.type, "softwareSystem")
    name = _esc_dsl(obj.name)
    desc = _esc_dsl(obj.description)
    tech = _tech_label(obj.technology_ids, tech_names)
    tech_arg = _esc_dsl(tech) if tech else None
    args = _build_dsl_args(name, desc, tech_arg)

    children = children_by_parent.get(obj.id, [])
    if children:
        lines.append(f"{pad}{a} = {kw} {args} {{")
        for child in children:
            _emit_dsl_obj(child, children_by_parent, tech_names, lines, indent + 2)
        lines.append(f"{pad}}}")
    else:
        lines.append(f"{pad}{a} = {kw} {args}")
