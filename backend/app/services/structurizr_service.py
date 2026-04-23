"""Minimal Structurizr DSL importer.

Supports the subset of DSL that maps cleanly onto ArchFlow's model:

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

from app.models.connection import Connection
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
            protocol=rel["technology"],
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
