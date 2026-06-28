"""Reusable prompt templates for grounded root cause analysis generation.

This module only defines prompt text and deterministic rendering helpers. It does
not call any model, parse any response, or embed transport concerns such as HTTP
or CLI handling.
"""

from __future__ import annotations

from prompting.types import PromptContext


SYSTEM_PROMPT_TEMPLATE = """You are GraphRCA, an evidence-grounded incident investigation assistant.

You must follow these rules exactly:

1. Use only the supplied evidence context.
2. Never invent evidence, events, systems, relationships, timings, or mitigations that are not present in the context.
3. Do not make unsupported causal claims. If the evidence is suggestive but not conclusive, say so explicitly.
4. Distinguish observed evidence from inferred conclusions.
5. Explicitly discuss competing hypotheses, including which are supported and which are ruled out or remain weaker.
6. Recommend actions only when they are supported by the supplied evidence or linked runbook guidance.
7. Whenever you reference evidence, include the relevant graph node IDs in citations.
8. Prefer precise evidence-backed statements over confident-sounding generalizations.
9. If evidence is missing or ambiguous, state the limitation instead of filling the gap.

Produce output in this order:

1. Structured RCA
2. Explanatory prose

The Structured RCA section must contain:
- root_cause
- evidence_summary
- supported_hypotheses
- ruled_out_hypotheses
- recommended_actions
- citations

The explanatory prose must remain grounded in the same supplied evidence and must not introduce uncited claims.
"""
"""Canonical system prompt for grounded RCA generation."""


USER_PROMPT_TEMPLATE = """Original user question:
{question}

Serialized prompt context:
{serialized_context}
"""
"""Canonical user prompt template for grounded RCA generation."""


def render_system_prompt() -> str:
    """Return the reusable system prompt for grounded RCA generation."""
    return SYSTEM_PROMPT_TEMPLATE


def render_user_prompt(context: PromptContext, *, question: str | None = None) -> str:
    """Render the user prompt with the original question and serialized context.

    Args:
        context: Structured prompt context produced from retrieval output.
        question: Optional explicit question override. When omitted, the question
            stored in `context.question` is used.

    Returns:
        A deterministic user prompt string suitable for downstream model clients.
    """

    resolved_question = (question or context.question).strip()
    serialized_context = context.model_dump_json(indent=2)
    return USER_PROMPT_TEMPLATE.format(
        question=resolved_question,
        serialized_context=serialized_context,
    )


__all__ = [
    "SYSTEM_PROMPT_TEMPLATE",
    "USER_PROMPT_TEMPLATE",
    "render_system_prompt",
    "render_user_prompt",
]
