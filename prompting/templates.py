"""Reusable prompt templates for grounded root cause analysis generation.

This module only defines prompt text and deterministic rendering helpers. It does
not call any model, parse any response, or embed transport concerns such as HTTP
or CLI handling.
"""

from __future__ import annotations

from prompting.serializer import PromptSerializer
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

Return only one JSON object.
Do not include markdown fences.
Do not include explanatory prose before or after the JSON object.

The JSON object must contain exactly these top-level fields:
- root_cause
- evidence_summary
- supported_hypotheses
- ruled_out_hypotheses
- recommended_actions
- citations

`root_cause` must be a non-empty string.
`evidence_summary`, `supported_hypotheses`, `ruled_out_hypotheses`, and `recommended_actions` must be arrays of strings.
`citations` must be an array of objects with `node_id`, `node_label`, and `explanation`.
"""
"""Canonical system prompt for grounded RCA generation."""


USER_PROMPT_TEMPLATE = """Original user question:
{question}

Serialized prompt context:
{serialized_context}

Return the RCA as JSON only, with this shape:
{{
  "root_cause": "string",
  "evidence_summary": ["string"],
  "supported_hypotheses": ["string"],
  "ruled_out_hypotheses": ["string"],
  "recommended_actions": ["string"],
  "citations": [
    {{
      "node_id": "string",
      "node_label": "string",
      "explanation": "string"
    }}
  ]
}}
"""
"""Canonical user prompt template for grounded RCA generation."""


_PROMPT_SERIALIZER = PromptSerializer()
"""Shared compact serializer for user-prompt evidence context."""


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
    serialized_context = _PROMPT_SERIALIZER.serialize(context)
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
