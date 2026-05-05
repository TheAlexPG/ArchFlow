"""DeepEval-compatible wrapper over LiteLLM for arbitrary judge models.

The wrapper lets eval suites swap the judge model independently from the agent
under test (spec §8.4): a small, cheap model (e.g. ``openai/gpt-4o-mini``)
typically scores answers produced by a larger, more expensive agent model.

The dependency is optional (``--extra evals``). When ``deepeval`` is not
installed we fall back to a thin shim that exposes the same surface
(``generate``, ``a_generate``, ``get_model_name``, ``load_model``) so unit
tests for the scaffolding itself stay importable without the extra. Tests
that actually call DeepEval metrics will, of course, need the extra installed.
"""

from __future__ import annotations

from typing import Any

try:
    from deepeval.models.base_model import DeepEvalBaseLLM  # type: ignore[import-not-found]

    _DEEPEVAL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in environments without --extra evals
    _DEEPEVAL_AVAILABLE = False

    class DeepEvalBaseLLM:  # type: ignore[no-redef]
        """Local fallback so the module imports without ``deepeval`` installed.

        Real DeepEval users get the genuine base class; CI without the extra
        gets enough of the shape (``__init__``, abstract-ish methods) to
        import and exercise non-LLM behaviour.
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


try:
    import litellm  # type: ignore[import-not-found]

    _LITELLM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LITELLM_AVAILABLE = False
    litellm = None  # type: ignore[assignment]


class DeepEvalLitellmWrapper(DeepEvalBaseLLM):
    """DeepEval LLM that routes calls through LiteLLM.

    Parameters
    ----------
    model:
        LiteLLM model identifier (e.g. ``openai/gpt-4o-mini``,
        ``anthropic/claude-3-5-haiku-latest``).
    api_key:
        Provider API key. Optional — LiteLLM also reads provider-specific env
        vars (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ...) if absent.
    base_url:
        Optional override for self-hosted / OpenAI-compatible gateways.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._api_key = api_key
        self._base_url = base_url

    def get_model_name(self) -> str:
        return self._model

    def load_model(self):  # noqa: D401 — DeepEval contract
        """DeepEval calls this to get the underlying client. We are the client."""
        return self

    def generate(self, prompt: str, schema: Any | None = None) -> str:
        """Synchronous completion. ``schema`` is accepted for API compatibility."""
        if not _LITELLM_AVAILABLE:  # pragma: no cover
            raise RuntimeError("litellm is required to call DeepEvalLitellmWrapper.generate")
        resp = litellm.completion(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""

    async def a_generate(self, prompt: str, schema: Any | None = None) -> str:
        """Async completion. ``schema`` is accepted for API compatibility."""
        if not _LITELLM_AVAILABLE:  # pragma: no cover
            raise RuntimeError("litellm is required to call DeepEvalLitellmWrapper.a_generate")
        resp = await litellm.acompletion(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
