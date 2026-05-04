"""LLM-backed reviewer for destructive operations (delete_*).

Wired in by every ``delete_*`` tool wrapper after the ``confirmed=True``
preview gate clears. Inputs:

* the proposed mutation (tool name + args, including the user-supplied
  ``reason`` field),
* the impact preview the handler computed in the first ``confirmed=False``
  pass (orphaned connections, dropped placements, child diagrams, etc.),
* the calling agent's recent message history — so the reviewer can judge
  whether the delete fits the agent's stated goal,
* the original user request, when available.

Output: ``DeleteVerdict {"verdict": "APPROVE"|"REJECT", "rationale": str}``.

When the runtime didn't wire an LLM client into ``ToolContext`` (tests,
direct service calls, or workspaces that intentionally disable the
reviewer) this helper auto-approves with a marker rationale so existing
flows keep working.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace as _replace
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


_REVIEWER_SYSTEM_PROMPT = """You are the **Destructive-Op Reviewer**.

An agent in this workspace is about to delete or unplace something. Your
job is to look at the proposed mutation, the agent's stated reason, the
impact preview, and the agent's recent activity, and decide whether the
delete is consistent with the user's goal.

Approve when:
- The reason matches what the agent is doing (e.g. "duplicate cleanup"
  and the recent activity shows the duplicate being identified).
- The impact is bounded and proportionate (e.g. unplacing one component
  with no orphan connections).
- The delete is idempotent / a no-op-style cleanup.

Reject when:
- The agent just created the same item one or two steps ago and is now
  immediately deleting it (creation-deletion churn — see trace 355785c7).
- The reason is generic ("oops", "no longer needed", "cleanup") and the
  impact is large (>5 orphan connections, dropping a non-empty diagram).
- The agent's recent activity contradicts the stated reason.
- The mutation would lose user-authored content (placements not made by
  the agent itself in this turn).

Output ONLY a JSON object:
```json
{"verdict": "APPROVE" | "REJECT", "rationale": "<one or two sentences>"}
```
"""


class DeleteVerdict(BaseModel):
    verdict: Literal["APPROVE", "REJECT"]
    rationale: str = Field(default="", max_length=2000)


def _short(obj: Any, n: int = 600) -> str:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:  # pragma: no cover — defensive
        s = repr(obj)
    return s if len(s) <= n else s[: n - 1] + "…"


def _format_recent_messages(messages: list[dict] | None, *, limit: int = 12) -> str:
    if not messages:
        return "_(no recent agent activity available)_"
    tail = messages[-limit:]
    lines: list[str] = []
    for m in tail:
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str) and content.strip():
            lines.append(f"- **{role}**: {content.strip()[:300]}")
        tcs = m.get("tool_calls") or []
        for tc in tcs:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name") or "?"
            args_raw = fn.get("arguments") or tc.get("arguments") or ""
            if isinstance(args_raw, str) and args_raw:
                lines.append(f"- **{role}.tool_call**: {name}({args_raw[:200]})")
            else:
                lines.append(f"- **{role}.tool_call**: {name}")
        if m.get("role") == "tool":
            tcid = m.get("tool_call_id") or "?"
            body = m.get("content")
            preview = _short(body, 200) if body else "(empty)"
            lines.append(f"- **tool_result** ({tcid}): {preview}")
    return "\n".join(lines) if lines else "_(no decodable messages)_"


async def review_destructive_op(
    *,
    ctx: Any,
    tool_name: str,
    args: BaseModel,
    impact: dict | None,
    reason: str,
    target_summary: str | None = None,
) -> DeleteVerdict:
    """Run the LLM reviewer for one destructive op.

    Falls back to APPROVE when no LLM client is wired in or the call
    fails — the reviewer is a safety net, not a hard barrier. Server-side
    enforcement still owns correctness (foreign keys, two-step preview).
    """
    llm = getattr(ctx, "llm_client", None)
    if llm is None:
        return DeleteVerdict(
            verdict="APPROVE",
            rationale="reviewer disabled (no LLM client in context)",
        )

    args_dict = args.model_dump(mode="json") if isinstance(args, BaseModel) else dict(args)
    # Strip the noisy ``confirmed`` echo from the args we feed the LLM.
    args_dict.pop("confirmed", None)

    user_block = "\n".join(
        [
            f"## Proposed mutation",
            f"- tool: `{tool_name}`",
            f"- args: `{_short(args_dict, 400)}`",
            f"- agent's stated reason: {reason!r}",
            f"- target summary: {target_summary or '(none)'}",
            "",
            f"## Impact preview",
            f"`{_short(impact or {}, 600)}`",
            "",
            f"## Calling agent ({getattr(ctx, 'agent_id', '?')}) — recent activity",
            _format_recent_messages(getattr(ctx, "agent_messages", None)),
            "",
            "Decide. Output ONLY the JSON verdict object.",
        ]
    )

    messages = [
        {"role": "system", "content": _REVIEWER_SYSTEM_PROMPT},
        {"role": "user", "content": user_block},
    ]

    call_meta = getattr(ctx, "call_metadata", None)
    if call_meta is None:
        # Reviewer needs metadata for cost / langfuse — without it we can
        # still call but tracing won't nest under this turn. Return early
        # rather than bypass the runtime's accounting.
        logger.warning(
            "destructive-op reviewer skipped: no call_metadata on ToolContext"
        )
        return DeleteVerdict(
            verdict="APPROVE",
            rationale="reviewer skipped (no call_metadata)",
        )

    # Mark reviewer node so it shows up cleanly in Langfuse.
    reviewer_meta = _replace(call_meta, node_name="destructive_review")

    try:
        result = await llm.acompletion(
            messages,
            metadata=reviewer_meta,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=400,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("destructive-op reviewer call failed: %s", exc)
        return DeleteVerdict(
            verdict="APPROVE",
            rationale=f"reviewer call failed: {exc}",
        )

    text = (result.text or "").strip()
    if not text:
        logger.warning("destructive-op reviewer returned empty text")
        return DeleteVerdict(
            verdict="APPROVE", rationale="reviewer returned empty response"
        )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("destructive-op reviewer non-json: %s", text[:200])
        return DeleteVerdict(
            verdict="APPROVE", rationale="reviewer non-json response"
        )

    try:
        return DeleteVerdict.model_validate(payload)
    except Exception as exc:
        logger.warning("destructive-op reviewer schema mismatch: %s", exc)
        return DeleteVerdict(
            verdict="APPROVE",
            rationale=f"reviewer schema invalid: {exc}",
        )
