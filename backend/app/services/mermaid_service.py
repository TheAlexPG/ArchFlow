"""Minimal Mermaid → ArchFlow importer.

Supports two flavors of the Mermaid syntax most commonly used for
architecture sketches:

1) C4 syntax:
       C4Context
         Person(u, "User")
         System(s, "Foo System", "Description")
         Container(c, "Web", "React")
         Rel(u, s, "Uses")

2) Flowchart syntax (TD/LR):
       flowchart TD
         A[User] --> B[Web API]
         B --> C[(Database)]
         B -->|HTTP| C
"""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.object import ModelObject, ObjectType

# ── C4 flavour ──────────────────────────────────────────

_C4_KEYWORDS = {
    "person": ObjectType.ACTOR,
    "system": ObjectType.SYSTEM,
    "system_ext": ObjectType.EXTERNAL_SYSTEM,
    "container": ObjectType.APP,
    "containerdb": ObjectType.STORE,
    "component": ObjectType.COMPONENT,
}

_C4_DECL = re.compile(
    r'^\s*(?P<kw>Person|System(?:_Ext)?|Container(?:Db)?|Component)'
    r'\(\s*(?P<id>[A-Za-z_][\w]*)\s*,'
    r'\s*"(?P<name>[^"]*)"'
    r'(?:\s*,\s*"(?P<desc_or_tech>[^"]*)")?'
    r'(?:\s*,\s*"(?P<desc>[^"]*)")?\s*\)\s*$'
)

_C4_REL = re.compile(
    r'^\s*Rel(?:_Back|_Neighbor|_Up|_Down|_Left|_Right)?\('
    r'\s*(?P<src>[A-Za-z_][\w]*)\s*,'
    r'\s*(?P<tgt>[A-Za-z_][\w]*)\s*,'
    r'\s*"(?P<label>[^"]*)"'
    r'(?:\s*,\s*"(?P<tech>[^"]*)")?\s*\)\s*$'
)

# ── Flowchart flavour ──────────────────────────────────

# Node token: `alias` or `alias[Label]`. Text grabs anything between the
# matching brackets, tolerating quoted and unquoted forms.
def _node_token(n: str) -> str:
    return (
        rf'(?P<id{n}>[A-Za-z_][\w]*)'
        rf'(?:\[\s*"?(?P<text{n}>[^\]"]*)"?\s*\])?'
    )


# Arrow with optional |label| in the middle: -->, -.->, ==>, -->|text|
_FLOW_EDGE = re.compile(
    r'^\s*' + _node_token("1") + r'\s*'
    r'(?P<arrow>-{1,3}>|==+>|-\.+->)'
    r'(?:\s*\|(?P<label>[^|]*)\|)?'
    r'\s*' + _node_token("2") + r'\s*$'
)

# Plain node declaration: A[Label]
_FLOW_NODE_DECL = re.compile(
    r'^\s*(?P<id>[A-Za-z_][\w]*)\s*\[\s*"?(?P<text>[^\]"]*)"?\s*\]\s*$'
)


class MermaidParseError(ValueError):
    pass


def _looks_like_c4(src: str) -> bool:
    return bool(re.search(r'^\s*C4(Context|Container|Component|Deployment)\b', src, re.MULTILINE))


def parse(src: str) -> tuple[list[dict], list[dict]]:
    if _looks_like_c4(src):
        return _parse_c4(src)
    return _parse_flowchart(src)


def _parse_c4(src: str) -> tuple[list[dict], list[dict]]:
    objects: list[dict] = []
    rels: list[dict] = []
    for raw_line in src.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        m = _C4_DECL.match(line)
        if m:
            kw = m.group("kw").lower()
            obj_type = _C4_KEYWORDS.get(kw, ObjectType.SYSTEM)
            # In C4 Mermaid, args after name are (description) or (technology, description).
            # We store description as-is and put technology into the tech field when we
            # detect a plausible short tag.
            d1 = m.group("desc_or_tech")
            d2 = m.group("desc")
            description = d2 or d1
            technology = d1 if d2 else None
            objects.append(
                {
                    "alias": m.group("id"),
                    "name": m.group("name"),
                    "type": obj_type,
                    "description": description,
                    "technology": [technology] if technology else None,
                }
            )
            continue
        m = _C4_REL.match(line)
        if m:
            rels.append(
                {
                    "source_alias": m.group("src"),
                    "target_alias": m.group("tgt"),
                    "label": m.group("label"),
                    "technology": m.group("tech"),
                }
            )
            continue
    return objects, rels


def _parse_flowchart(src: str) -> tuple[list[dict], list[dict]]:
    objects_by_alias: dict[str, dict] = {}
    rels: list[dict] = []

    def ensure(alias: str, text: str | None = None) -> None:
        if alias in objects_by_alias:
            if text and not objects_by_alias[alias].get("name"):
                objects_by_alias[alias]["name"] = text
            return
        objects_by_alias[alias] = {
            "alias": alias,
            "name": text or alias,
            "type": ObjectType.SYSTEM,
            "description": None,
            "technology": None,
        }

    for raw_line in src.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if re.match(r'^\s*(flowchart|graph)\b', line, re.IGNORECASE):
            continue

        m = _FLOW_EDGE.match(line)
        if m:
            ensure(m.group("id1"), m.group("text1"))
            ensure(m.group("id2"), m.group("text2"))
            rels.append(
                {
                    "source_alias": m.group("id1"),
                    "target_alias": m.group("id2"),
                    "label": m.group("label"),
                    "technology": None,
                }
            )
            continue

        m = _FLOW_NODE_DECL.match(line)
        if m:
            ensure(m.group("id"), m.group("text"))
            continue

    return list(objects_by_alias.values()), rels


async def import_mermaid(db: AsyncSession, src: str) -> dict:
    parsed_objects, parsed_rels = parse(src)
    alias_to_id: dict[str, uuid.UUID] = {}

    for obj in parsed_objects:
        model_obj = ModelObject(
            name=obj["name"],
            type=obj["type"],
            description=obj.get("description"),
            # TODO(tech-catalog): resolve obj["technology"] text against the
            # catalog once importers know their target workspace.
        )
        db.add(model_obj)
        await db.flush()
        alias_to_id[obj["alias"]] = model_obj.id

    created_rels = 0
    for rel in parsed_rels:
        src_id = alias_to_id.get(rel["source_alias"])
        tgt_id = alias_to_id.get(rel["target_alias"])
        if not src_id or not tgt_id:
            continue
        conn = Connection(
            source_id=src_id,
            target_id=tgt_id,
            label=rel["label"],
            protocol=rel.get("technology"),
        )
        db.add(conn)
        created_rels += 1

    await db.flush()
    return {
        "objects_created": len(alias_to_id),
        "connections_created": created_rels,
        "alias_map": {k: str(v) for k, v in alias_to_id.items()},
    }
