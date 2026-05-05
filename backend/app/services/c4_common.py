"""Shared C4 helpers for the Mermaid + PlantUML exporters.

Mermaid C4 and C4-PlantUML use the same macro vocabulary (Person, System,
Container, Component, *_Boundary, Rel/BiRel) and almost the same arg shapes.
This module owns the vocabulary so the two exporters stay in lock-step.
"""

import uuid

from app.models.diagram import DiagramType
from app.models.object import ObjectType

# Macros whose third positional arg is technology, not description.
# (Container family + Component family in C4-PlantUML / Mermaid C4.)
_KW_WITH_TECH_ARG = frozenset(
    {
        "Container",
        "ContainerDb",
        "ContainerQueue",
        "Component",
        "ComponentDb",
        "ComponentQueue",
    }
)


def alias(obj_id: uuid.UUID) -> str:
    """Stable, parser-safe alias derived from the object's UUID."""
    return f"n_{obj_id.hex[:8]}"


def c4_keyword(obj_type: ObjectType, diagram_type: DiagramType) -> str:
    """Map an ArchFlow object type to the appropriate C4 macro for `diagram_type`.

    Why diagram-aware: ContainerDb / Component aren't defined in C4Context /
    C4_Context.puml, so emitting them under a context view crashes some
    renderers. We collapse APP/COMPONENT/STORE down to the L1 vocabulary
    when rendering at landscape/context level, and only let the richer
    macros through when the view actually defines them.
    """
    if obj_type == ObjectType.GROUP:
        return "System_Boundary"
    if obj_type == ObjectType.ACTOR:
        return "Person"
    if obj_type == ObjectType.EXTERNAL_SYSTEM:
        return "System_Ext"
    if obj_type == ObjectType.SYSTEM:
        return "System"

    is_landscape_or_context = diagram_type in (
        DiagramType.SYSTEM_LANDSCAPE,
        DiagramType.SYSTEM_CONTEXT,
    )
    if is_landscape_or_context:
        return "SystemDb" if obj_type == ObjectType.STORE else "System"
    if diagram_type == DiagramType.CONTAINER:
        if obj_type == ObjectType.STORE:
            return "ContainerDb"
        return "Container"  # APP + COMPONENT both render as Container at L2
    if diagram_type == DiagramType.COMPONENT:
        if obj_type == ObjectType.STORE:
            return "ContainerDb"
        if obj_type == ObjectType.APP:
            return "Container"
        return "Component"
    return "System"


def is_boundary_kw(kw: str) -> bool:
    return kw.endswith("_Boundary")


def kw_takes_tech_arg(kw: str) -> bool:
    return kw in _KW_WITH_TECH_ARG


def esc_c4_arg(s: str | None) -> str:
    """Make `s` safe to drop into a C4 macro double-quoted arg.

    Mermaid C4 / C4-PlantUML strings have no escape sequences — quotes and
    backslashes pass through to the renderer's regex. Newlines also tend to
    break the macro parser. We swap the dangerous chars for visually similar
    safe ones rather than dropping content silently.
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


def build_c4_args(
    kw: str,
    obj_alias: str,
    name: str,
    tech: str | None,
    description: str | None,
) -> str:
    """Build the comma-separated arg list for a C4 element macro call.

    Boundary macros use a different shape (`(alias, "name") { ... }`) and are
    rendered separately; this helper covers the Person / System / Container /
    Component families.
    """
    parts = [obj_alias, f'"{name}"']
    if kw_takes_tech_arg(kw):
        # Container/Component family: third arg is technology, fourth is description.
        parts.append(f'"{tech or ""}"')
        if description:
            parts.append(f'"{description}"')
    else:
        # Person / System / SystemDb / System_Ext: no tech slot. Fold tech into
        # the description so the AI consumer doesn't lose it.
        merged = description
        if tech and description:
            merged = f"{description} ({tech})"
        elif tech:
            merged = tech
        if merged:
            parts.append(f'"{merged}"')
    return ", ".join(parts)
