"""C4-PlantUML exporter for ArchFlow diagrams.

Emits PlantUML source that pulls in the C4-PlantUML stdlib so any PlantUML
renderer (plantuml.com, Kroki, the IntelliJ plugin) can render the result
without further configuration.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import ConnectionDirection
from app.models.diagram import Diagram, DiagramType
from app.services.c4_common import (
    alias as _alias,
)
from app.services.c4_common import (
    build_c4_args,
    c4_keyword,
    esc_c4_arg,
    is_boundary_kw,
)

_INCLUDE = {
    DiagramType.SYSTEM_LANDSCAPE: "C4_Context.puml",
    DiagramType.SYSTEM_CONTEXT: "C4_Context.puml",
    DiagramType.CONTAINER: "C4_Container.puml",
    DiagramType.COMPONENT: "C4_Component.puml",
    DiagramType.CUSTOM: "C4_Container.puml",
}


def _tech_label(ids, tech_names: dict[uuid.UUID, str]) -> str | None:
    if not ids:
        return None
    names = [tech_names[i] for i in ids if i in tech_names]
    return ", ".join(names) if names else None


def _build_parent_index(placements: list) -> tuple[dict, list]:
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


async def export_plantuml(db: AsyncSession, diagram: Diagram) -> str:
    from app.services import diagram_service

    payload = await diagram_service.get_diagram_payload(db, diagram)
    placements = payload["placements"]
    connections = payload["connections"]
    tech_names = payload["tech_names"]

    include = _INCLUDE.get(diagram.type, "C4_Container.puml")
    lines: list[str] = ["@startuml"]
    lines.append(
        f"!include https://raw.githubusercontent.com/plantuml-stdlib/"
        f"C4-PlantUML/master/{include}"
    )
    lines.append("' Exported from ArchFlow")
    lines.append(f"' diagram_id: {diagram.id}")
    lines.append(f"' diagram_type: {diagram.type.value}")
    lines.append(
        f"' objects: {len(placements)}; connections: {len(connections)}"
    )
    lines.append(f'title {esc_c4_arg(diagram.name)}')

    children_by_parent, top_level = _build_parent_index(placements)

    for p in top_level:
        _emit_placement(
            p, diagram.type, tech_names, children_by_parent, lines, indent=0
        )

    for c in connections:
        src = _alias(c.source_id)
        tgt = _alias(c.target_id)
        label = esc_c4_arg(c.label)
        tech = _tech_label(c.protocol_ids, tech_names)
        rel_kw = "BiRel" if c.direction == ConnectionDirection.BIDIRECTIONAL else "Rel"
        if tech:
            lines.append(f'{rel_kw}({src}, {tgt}, "{label}", "{esc_c4_arg(tech)}")')
        else:
            lines.append(f'{rel_kw}({src}, {tgt}, "{label}")')

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def _emit_placement(
    placement,
    diagram_type: DiagramType,
    tech_names: dict,
    children_by_parent: dict,
    lines: list[str],
    indent: int,
) -> None:
    obj = placement.object
    pad = "  " * indent
    a = _alias(obj.id)
    kw = c4_keyword(obj.type, diagram_type)
    name = esc_c4_arg(obj.name)
    desc = esc_c4_arg(obj.description)
    tech = _tech_label(obj.technology_ids, tech_names)
    tech_arg = esc_c4_arg(tech) if tech else None

    lines.append(
        f"{pad}' {a} = {obj.id} (type={obj.type.value}, status={obj.status.value})"
    )

    if is_boundary_kw(kw):
        lines.append(f'{pad}{kw}({a}, "{name}") {{')
        for child in children_by_parent.get(obj.id, []):
            _emit_placement(
                child, diagram_type, tech_names, children_by_parent, lines, indent + 1
            )
        lines.append(f"{pad}}}")
        return

    args = build_c4_args(kw, a, name, tech_arg, desc)
    lines.append(f"{pad}{kw}({args})")
