"""Tool catalog for all agent nodes.

Importing this package side-effects: every submodule below is imported
eagerly so that the ``@tool`` decorator side-effects (calls to
``register_tool``) populate the registry in ``base.py``.

Without this, agents that reference tools by name (delegate_to_researcher,
search_existing_objects, web_fetch, …) would crash at runtime with
``tool not registered: <name>`` — the LLM sees the tool definition in the
prompt and calls it, but the executor can't find the registered handler.

Order is alphabetical; intra-module dependencies are limited to ``base``.
"""

from app.agents.tools import (  # noqa: F401 — side-effect imports
    base,
    drafts_tools,
    model_tools,
    reasoning_tools,
    search_tools,
    view_tools,
    web_fetch,
)
