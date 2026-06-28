"""Parse raw LLM output into structured RCA drafts.

This module is intentionally limited to output interpretation and validation. It
does not build prompts, call llama.cpp, or perform retrieval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from prompting.types import RcaCitation, RcaDraft


_REQUIRED_JSON_FIELDS = frozenset(
    {
        "root_cause",
        "evidence_summary",
        "supported_hypotheses",
        "ruled_out_hypotheses",
        "recommended_actions",
        "citations",
    }
)
"""Fields that must be present when the model returns structured RCA JSON."""

_SECTION_ALIASES: dict[str, str] = {
    "root cause": "root_cause",
    "root_cause": "root_cause",
    "evidence summary": "evidence_summary",
    "evidence_summary": "evidence_summary",
    "supported hypotheses": "supported_hypotheses",
    "supported_hypotheses": "supported_hypotheses",
    "ruled out hypotheses": "ruled_out_hypotheses",
    "ruled_out_hypotheses": "ruled_out_hypotheses",
    "recommended actions": "recommended_actions",
    "recommended_actions": "recommended_actions",
}
"""Loose section-name mapping used for plaintext fallback parsing."""


class RcaParsingError(ValueError):
    """Raised when raw model output cannot be parsed into a valid structured RCA."""


@dataclass(slots=True)
class RcaParser:
    """Parse raw model output into validated `RcaDraft` instances.

    The parser prefers structured JSON because it is deterministic and easiest to
    validate. When strict parsing fails, the parser falls back to best-effort
    plaintext extraction and finally to a safe failure draft that preserves the
    original model output for debugging.
    """

    fallback_root_cause: str = "Unable to parse a grounded root cause from the model output."

    def parse(self, raw_model_output: str) -> RcaDraft:
        """Parse raw model output and always return a safe `RcaDraft`.

        This method never raises parsing failures to the caller. It attempts strict
        JSON parsing first, then a lightweight plaintext extraction pass, and
        finally returns a fallback RCA draft when parsing is not reliable.
        """

        try:
            return self.parse_strict(raw_model_output)
        except RcaParsingError as exc:
            fallback = self._parse_plaintext_fallback(raw_model_output)
            if fallback is not None:
                return fallback
            return self._safe_fallback(raw_model_output, str(exc))

    def parse_strict(self, raw_model_output: str) -> RcaDraft:
        """Parse raw model output and raise `RcaParsingError` on failure."""
        normalized_output = raw_model_output.strip()
        if not normalized_output:
            raise RcaParsingError("Model output was empty.")

        json_payload = self._extract_json_payload(normalized_output)
        if json_payload is None:
            raise RcaParsingError("Model output did not contain a valid JSON object.")

        return self._draft_from_json_payload(json_payload, raw_model_output=normalized_output)

    def _extract_json_payload(self, raw_model_output: str) -> dict[str, Any] | None:
        """Extract the first valid JSON object from raw model output."""
        fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_model_output, re.DOTALL | re.IGNORECASE)
        if fenced_match:
            try:
                payload = json.loads(fenced_match.group(1))
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                return payload

        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", raw_model_output):
            start = match.start()
            try:
                payload, _ = decoder.raw_decode(raw_model_output[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return None

    def _draft_from_json_payload(self, payload: dict[str, Any], *, raw_model_output: str) -> RcaDraft:
        """Validate one structured JSON payload and convert it into an `RcaDraft`."""
        missing_fields = sorted(field for field in _REQUIRED_JSON_FIELDS if field not in payload)
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise RcaParsingError(f"Structured RCA JSON is missing required fields: {missing}.")

        root_cause = self._require_non_empty_string(payload.get("root_cause"), field_name="root_cause")
        evidence_summary = self._normalize_string_list(payload.get("evidence_summary"), field_name="evidence_summary")
        supported_hypotheses = self._normalize_string_list(
            payload.get("supported_hypotheses"),
            field_name="supported_hypotheses",
        )
        ruled_out_hypotheses = self._normalize_string_list(
            payload.get("ruled_out_hypotheses"),
            field_name="ruled_out_hypotheses",
        )
        recommended_actions = self._normalize_string_list(
            payload.get("recommended_actions"),
            field_name="recommended_actions",
        )
        citations = self._normalize_citations(payload.get("citations"))

        try:
            return RcaDraft(
                root_cause=root_cause,
                evidence_summary=evidence_summary,
                supported_hypotheses=supported_hypotheses,
                ruled_out_hypotheses=ruled_out_hypotheses,
                recommended_actions=recommended_actions,
                citations=citations,
                raw_model_output=raw_model_output,
            )
        except ValidationError as exc:
            raise RcaParsingError(f"Structured RCA JSON failed model validation: {exc}") from exc

    def _normalize_citations(self, citations_payload: Any) -> list[RcaCitation]:
        """Validate and normalize structured citation payloads."""
        if not isinstance(citations_payload, list):
            raise RcaParsingError("Field 'citations' must be a list.")

        citations: list[RcaCitation] = []
        for index, item in enumerate(citations_payload):
            if not isinstance(item, dict):
                raise RcaParsingError(f"Citation at index {index} must be an object.")
            try:
                citations.append(RcaCitation.model_validate(item))
            except ValidationError as exc:
                raise RcaParsingError(f"Citation at index {index} is invalid: {exc}") from exc
        return citations

    def _normalize_string_list(self, value: Any, *, field_name: str) -> list[str]:
        """Return a validated list of non-empty strings for one structured RCA field."""
        if not isinstance(value, list):
            raise RcaParsingError(f"Field '{field_name}' must be a list.")

        normalized: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise RcaParsingError(f"Field '{field_name}' contains an empty or non-string item at index {index}.")
            normalized.append(item.strip())
        return normalized

    def _require_non_empty_string(self, value: Any, *, field_name: str) -> str:
        """Return one required string field or raise a parsing error."""
        if not isinstance(value, str) or not value.strip():
            raise RcaParsingError(f"Field '{field_name}' must be a non-empty string.")
        return value.strip()

    def _parse_plaintext_fallback(self, raw_model_output: str) -> RcaDraft | None:
        """Best-effort fallback for non-JSON responses using section-based extraction."""
        sections = self._extract_plaintext_sections(raw_model_output)
        root_cause = sections.get("root_cause")
        if not root_cause:
            return None

        citations = self._extract_inline_citations(raw_model_output)
        try:
            return RcaDraft(
                root_cause=root_cause,
                evidence_summary=self._coerce_section_list(sections.get("evidence_summary")),
                supported_hypotheses=self._coerce_section_list(sections.get("supported_hypotheses")),
                ruled_out_hypotheses=self._coerce_section_list(sections.get("ruled_out_hypotheses")),
                recommended_actions=self._coerce_section_list(sections.get("recommended_actions")),
                citations=citations,
                raw_model_output=raw_model_output.strip(),
            )
        except ValidationError:
            return None

    def _extract_plaintext_sections(self, raw_model_output: str) -> dict[str, str | list[str]]:
        """Extract common RCA sections from plaintext output."""
        sections: dict[str, str | list[str]] = {}
        current_section: str | None = None
        current_items: list[str] = []

        for raw_line in raw_model_output.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            heading_match = re.match(r"^[#*\-]*\s*([A-Za-z_ ]+)\s*:\s*(.*)$", line)
            if heading_match:
                heading = heading_match.group(1).strip().lower()
                alias = _SECTION_ALIASES.get(heading)
                trailing_value = heading_match.group(2).strip()
                if alias is not None:
                    if current_section is not None and current_items and current_section != "root_cause":
                        sections[current_section] = current_items[:]
                    current_section = alias
                    current_items = []
                    if alias == "root_cause":
                        if trailing_value:
                            sections["root_cause"] = trailing_value
                        continue
                    if trailing_value:
                        current_items.append(trailing_value)
                    continue

            bullet_match = re.match(r"^(?:[-*]|\d+\.)\s+(.*\S)\s*$", line)
            if bullet_match and current_section is not None and current_section != "root_cause":
                current_items.append(bullet_match.group(1).strip())
                continue

            if current_section == "root_cause" and "root_cause" not in sections:
                sections["root_cause"] = line
                continue

            if current_section is not None and current_section != "root_cause":
                current_items.append(line)

        if current_section is not None and current_items and current_section != "root_cause":
            sections[current_section] = current_items[:]
        return sections

    def _coerce_section_list(self, value: str | list[str] | None) -> list[str]:
        """Normalize one fallback section value into a clean list of strings."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [item.strip() for item in value if item.strip()]

    def _extract_inline_citations(self, raw_model_output: str) -> list[RcaCitation]:
        """Extract simple inline node-ID mentions into lightweight citation objects."""
        node_ids = sorted(set(re.findall(r"\b[a-z]+:[A-Za-z0-9_.:-]+\b", raw_model_output)))
        citations: list[RcaCitation] = []
        for node_id in node_ids:
            label = node_id.split(":", 1)[0].capitalize()
            try:
                citations.append(
                    RcaCitation(
                        node_id=node_id,
                        node_label=label,
                        explanation="Citation inferred from node ID referenced in model output.",
                    )
                )
            except ValidationError:
                continue
        return citations

    def _safe_fallback(self, raw_model_output: str, error_message: str) -> RcaDraft:
        """Return a non-throwing fallback RCA draft when parsing cannot be trusted."""
        return RcaDraft(
            root_cause=self.fallback_root_cause,
            evidence_summary=[f"Parsing failed: {error_message}"],
            supported_hypotheses=[],
            ruled_out_hypotheses=[],
            recommended_actions=[],
            citations=[],
            raw_model_output=raw_model_output.strip() or "<empty model output>",
        )


__all__ = ["RcaParser", "RcaParsingError"]
