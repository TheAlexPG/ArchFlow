"""AI-assisted analysis for model objects.

Wraps the Anthropic SDK to produce structured insights (summary +
recommendations) for a ModelObject, given its neighborhood of connections.
Disabled gracefully when ANTHROPIC_API_KEY is not configured.
"""

import uuid
from typing import Any

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import object_service

_SYSTEM_PROMPT = (
    "You are an architecture assistant helping a software architect understand a "
    "C4 model object. Given structured facts about the object and its neighbors, "
    "you produce:\n"
    "  1) a 1-2 sentence summary of what this component is and where it sits,\n"
    "  2) 3-5 observations about gaps, risks, or inaccuracies to double-check,\n"
    "  3) 2-4 concrete recommendations to improve the model or the system.\n\n"
    "Be specific and concise. Don't invent facts; if something is unknown, say so."
)


def is_available() -> bool:
    return bool(settings.anthropic_api_key)


async def _build_context(
    db: AsyncSession, object_id: uuid.UUID
) -> dict[str, Any]:
    obj = await object_service.get_object(db, object_id)
    if not obj:
        return {}
    deps = await object_service.get_dependencies(db, object_id)

    def edge_summary(c: Any, side: str) -> dict:
        other = c.source if side == "upstream" else c.target
        return {
            "direction": side,
            "label": c.label,
            "protocol": c.protocol,
            "other": {
                "name": other.name,
                "type": other.type.value if hasattr(other.type, "value") else str(other.type),
            },
        }

    return {
        "object": {
            "name": obj.name,
            "type": obj.type.value if hasattr(obj.type, "value") else str(obj.type),
            "scope": obj.scope.value if hasattr(obj.scope, "value") else str(obj.scope),
            "status": obj.status.value if hasattr(obj.status, "value") else str(obj.status),
            "description_html": obj.description,
            "technology_ids": [str(t) for t in (obj.technology_ids or [])],
            "tags": obj.tags,
            "owner_team": obj.owner_team,
        },
        "upstream": [edge_summary(c, "upstream") for c in deps["upstream"]],
        "downstream": [edge_summary(c, "downstream") for c in deps["downstream"]],
    }


async def get_insights(db: AsyncSession, object_id: uuid.UUID) -> dict:
    """Return {"summary": str, "observations": [...], "recommendations": [...]}.

    Raises RuntimeError if the API key is not configured — the caller should
    translate that into an HTTP 503.
    """
    if not is_available():
        raise RuntimeError("Anthropic API key not configured")

    context = await _build_context(db, object_id)
    if not context:
        raise RuntimeError("Object not found")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_prompt = (
        "Analyze this C4 object and its neighbors. Reply as JSON matching this shape:\n"
        '{"summary": "...", "observations": ["..."], "recommendations": ["..."]}\n\n'
        "Object data:\n"
        f"{context}"
    )

    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Claude returns a list of content blocks; we only sent text so take first.
    raw_text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    return _parse_insights(raw_text)


def _parse_insights(raw: str) -> dict:
    """Parse the model's JSON reply, tolerating surrounding prose/fences."""
    import json
    import re

    cleaned = raw.strip()
    # Strip ```json ... ``` fences if present.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)

    # Last-ditch extraction: grab the first JSON object substring.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    # Fallback: surface the raw text so the UI can still show something.
    return {
        "summary": cleaned[:500],
        "observations": [],
        "recommendations": [],
    }
