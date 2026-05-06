"""Mermaid bridge — both directions.

Importer: parses Mermaid C4 and flowchart syntax into ArchFlow rows.
Exporter: walks a diagram's placements + connections and emits Mermaid
text (C4 syntax for C4 diagram types, flowchart for `custom`).
"""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection, ConnectionDirection
from app.models.diagram import Diagram, DiagramType
from app.models.object import ModelObject, ObjectType
from app.services.c4_common import (
    alias as _alias,
)
from app.services.c4_common import (
    build_c4_args,
    c4_keyword,
    esc_c4_arg,
    is_boundary_kw,
)

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
            # TODO(tech-catalog): resolve rel.get("technology") text against the
            # catalog once importers know their target workspace.
            protocol_ids=None,
        )
        db.add(conn)
        created_rels += 1

    await db.flush()
    return {
        "objects_created": len(alias_to_id),
        "connections_created": created_rels,
        "alias_map": {k: str(v) for k, v in alias_to_id.items()},
    }


# ── Exporter ────────────────────────────────────────────


_C4_HEADER = {
    DiagramType.SYSTEM_LANDSCAPE: "C4Context",
    DiagramType.SYSTEM_CONTEXT: "C4Context",
    DiagramType.CONTAINER: "C4Container",
    DiagramType.COMPONENT: "C4Component",
}


def _esc_flow_label(s: str | None) -> str:
    """Sanitize a Mermaid flowchart label.

    Labels appear inside `["..."]` node decls and `|...|` edge labels. We
    swap the chars that terminate or unbalance those wrappers (`]`, `[`,
    `|`), drop newlines, and swap backslashes to dodge any escape
    interpretation.
    """
    if not s:
        return ""
    return (
        s.replace("\\", "/")
        .replace('"', "'")
        .replace("[", "(")
        .replace("]", ")")
        .replace("|", "/")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def _tech_label(ids, tech_names: dict[uuid.UUID, str]) -> str | None:
    if not ids:
        return None
    names = [tech_names[i] for i in ids if i in tech_names]
    return ", ".join(names) if names else None


async def export_mermaid(db: AsyncSession, diagram: Diagram) -> str:
    from app.services import diagram_service  # local import to avoid cycle

    payload = await diagram_service.get_diagram_payload(db, diagram)
    if diagram.type == DiagramType.CUSTOM:
        return _export_flowchart(diagram, payload)
    return _export_c4(diagram, payload)


def _header_comments(diagram: Diagram, payload: dict) -> list[str]:
    return [
        "%% Exported from ArchFlow",
        f"%% diagram_id: {diagram.id}",
        f"%% diagram_type: {diagram.type.value}",
        f"%% diagram_name: {esc_c4_arg(diagram.name)}",
        f"%% objects: {len(payload['placements'])}; "
        f"connections: {len(payload['connections'])}",
    ]


def _build_parent_index(placements: list) -> tuple[dict, list]:
    """Return (children_by_parent_id, top_level_placements).

    A placement is "top-level" when its object has no parent, or its parent
    isn't placed on this diagram.
    """
    placed_ids = {p.object_id for p in placements}
    children_by_parent: dict = {}
    top_level: list = []
    for p in placements:
        parent_id = p.object.parent_id
        if parent_id and parent_id in placed_ids:
            children_by_parent.setdefault(parent_id, []).append(p)
        else:
            top_level.append(p)
    return children_by_parent, top_level


def _export_c4(diagram: Diagram, payload: dict) -> str:
    placements = payload["placements"]
    connections = payload["connections"]
    tech_names = payload["tech_names"]
    header_kw = _C4_HEADER[diagram.type]

    lines: list[str] = list(_header_comments(diagram, payload))
    lines.append("")
    lines.append(header_kw)
    lines.append(f"  title {esc_c4_arg(diagram.name)}")

    children_by_parent, top_level = _build_parent_index(placements)

    for p in top_level:
        _emit_c4_placement(
            p, diagram.type, tech_names, children_by_parent, lines, indent=2
        )

    for c in connections:
        src = _alias(c.source_id)
        tgt = _alias(c.target_id)
        label = esc_c4_arg(c.label)
        tech = _tech_label(c.protocol_ids, tech_names)
        rel_kw = "BiRel" if c.direction == ConnectionDirection.BIDIRECTIONAL else "Rel"
        if tech:
            lines.append(f'  {rel_kw}({src}, {tgt}, "{label}", "{esc_c4_arg(tech)}")')
        else:
            lines.append(f'  {rel_kw}({src}, {tgt}, "{label}")')

    return "\n".join(lines) + "\n"


def _emit_c4_placement(
    placement,
    diagram_type: DiagramType,
    tech_names: dict,
    children_by_parent: dict,
    lines: list[str],
    indent: int,
) -> None:
    obj = placement.object
    pad = " " * indent
    a = _alias(obj.id)
    kw = c4_keyword(obj.type, diagram_type)
    name = esc_c4_arg(obj.name)
    desc = esc_c4_arg(obj.description)
    tech = _tech_label(obj.technology_ids, tech_names)
    tech_arg = esc_c4_arg(tech) if tech else None

    lines.append(
        f"{pad}%% {a} = {obj.id} (type={obj.type.value}, status={obj.status.value})"
    )

    if is_boundary_kw(kw):
        lines.append(f'{pad}{kw}({a}, "{name}") {{')
        for child in children_by_parent.get(obj.id, []):
            _emit_c4_placement(
                child, diagram_type, tech_names, children_by_parent, lines, indent + 2
            )
        lines.append(f"{pad}}}")
        return

    args = build_c4_args(kw, a, name, tech_arg, desc)
    lines.append(f"{pad}{kw}({args})")


def _export_flowchart(diagram: Diagram, payload: dict) -> str:
    """Custom diagram → Mermaid flowchart.

    The output is restricted to `[label]` node declarations and `-->` arrows so
    it round-trips through `mermaid_service.parse()`. The richer shapes
    (`((actor))`, `[(db)]`, `{{ext}}`) the parser doesn't accept yet are dropped
    in favour of comments that record the original ObjectType for any AI
    consumer that needs to recover it.
    """
    placements = payload["placements"]
    connections = payload["connections"]

    lines: list[str] = list(_header_comments(diagram, payload))
    lines.append("")
    lines.append("flowchart TD")

    for p in placements:
        obj = p.object
        alias = _alias(obj.id)
        name = _esc_flow_label(obj.name)
        lines.append(
            f"  %% {alias} = {obj.id} (type={obj.type.value}, status={obj.status.value})"
        )
        lines.append(f'  {alias}["{name}"]')

    for c in connections:
        src = _alias(c.source_id)
        tgt = _alias(c.target_id)
        label = _esc_flow_label(c.label)
        edge = f"  {src} -->|{label}| {tgt}" if label else f"  {src} --> {tgt}"
        lines.append(edge)
        if c.direction == ConnectionDirection.BIDIRECTIONAL:
            back = (
                f"  {tgt} -->|{label}| {src}" if label else f"  {tgt} --> {src}"
            )
            lines.append(back)

    return "\n".join(lines) + "\n"
