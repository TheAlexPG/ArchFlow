"""AI insights — Phase 1 wrapper that delegates to the diagram-explainer agent.
Preserves the existing {summary, observations, recommendations} response shape for back-compat.

Phase 2: deprecate this entirely; frontend should call the agent directly via
/api/v1/agents/diagram-explainer/invoke.
"""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import ActorRef, ChatContext, InvokeRequest, invoke


def is_available() -> bool:
    """True if the diagram-explainer agent is registered."""
    from app.agents import registry
    try:
        registry.get("diagram-explainer")
        return True
    except KeyError:
        return False


async def get_insights(
    db: AsyncSession, object_id: uuid.UUID, *, actor: ActorRef | None = None
) -> dict:
    """Delegate to diagram-explainer agent. Map its output to the legacy shape.

    If actor not provided (legacy callers without auth context), use a synthetic
    system actor. Phase 1 simplification: legacy endpoint will still need real
    auth — caller should pass actor.
    """
    if not is_available():
        raise RuntimeError("diagram-explainer agent not registered")

    # The legacy prompt asked for: 1-2 sentence summary + 3-5 observations + 2-4 recommendations.
    # Pass that style as the user message to diagram-explainer:
    message = (
        "Provide insights for this C4 model object. Reply in three sections: "
        "1) Summary (1-2 sentences). "
        "2) Observations (3-5 bullets about gaps, risks, inaccuracies). "
        "3) Recommendations (2-4 concrete improvements). "
        "Keep responses concise and grounded in the object's actual data."
    )

    resolved_actor = actor or _system_actor()
    req = InvokeRequest(
        agent_id="diagram-explainer",
        actor=resolved_actor,
        workspace_id=resolved_actor.workspace_id,
        chat_context=ChatContext(kind="object", id=object_id),
        message=message,
        mode="read_only",
    )

    result = await invoke(req, db=db)
    return _parse_legacy_shape(result.final_message)


def _system_actor() -> ActorRef:
    """Synthetic actor for legacy callers without auth (e.g., API key with insights perm).
    Use a special user_id indicating 'system insights' for audit clarity."""
    return ActorRef(
        kind="user",
        id=uuid.UUID(int=0),
        workspace_id=uuid.UUID(int=0),
        agent_access="read_only",
    )


def _parse_legacy_shape(markdown_text: str) -> dict:
    """Parse the LLM markdown sections into {summary, observations, recommendations}.

    Heuristic: look for headers like '## Summary' / '**Observations**' / '1. ' etc.
    Best-effort. If parsing fails, fall back to
    {summary: full_text, observations: [], recommendations: []}.
    """
    summary, observations, recommendations = "", [], []

    # Look for 'Summary'/'Observations'/'Recommendations' sections case-insensitive.
    sections = re.split(
        r"(?im)^\s*(?:#+\s*|\*\*\s*)?(summary|observations|recommendations)(?:\s*:|\s*\*\*)?\s*$",
        markdown_text,
    )

    # Walk pairs (header, content). Bullet points start with '-', '*', '•', or '1.'/'2.'.
    bullet_re = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+(.+)$", re.MULTILINE)

    if len(sections) >= 3:
        for i in range(1, len(sections), 2):
            header = sections[i].lower()
            body = sections[i + 1] if i + 1 < len(sections) else ""
            if "summary" in header:
                summary = body.strip()[:500]
            elif "observation" in header:
                observations = [m.group(1).strip() for m in bullet_re.finditer(body)][:5]
            elif "recommend" in header:
                recommendations = [m.group(1).strip() for m in bullet_re.finditer(body)][:4]

    if not summary and not observations and not recommendations:
        # Fallback: entire response as summary, no parsed lists.
        summary = markdown_text.strip()[:500]

    return {"summary": summary, "observations": observations, "recommendations": recommendations}
