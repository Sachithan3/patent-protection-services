"""LLM orchestration for grounded patent infringement reports."""

import json
import logging
from typing import Any, Mapping, Sequence

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.rag_prompt import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


def format_retrieved_context(top_patents: Sequence[Mapping[str, Any]]) -> str:
    """Format retrieval results into explicit, claim-numbered legal context."""
    sections: list[str] = []
    for patent in top_patents:
        claims = patent.get("claims", [])
        claim_lines = "\n".join(
            f"  Claim {index}: {claim}" for index, claim in enumerate(claims, start=1)
        )
        sections.append(
            "\n".join(
                [
                    f"Patent ID: {patent.get('patent_id', 'UNKNOWN')}",
                    f"Title: {patent.get('title', 'UNKNOWN')}",
                    f"Category: {patent.get('category', 'UNKNOWN')}",
                    f"Abstract: {patent.get('abstract', '')}",
                    "Claims:",
                    claim_lines or "  No claims supplied.",
                ]
            )
        )
    return "\n\n--- RETRIEVED PATENT ---\n\n".join(sections)


def _extract_text(response: Any) -> str:
    """Extract generated text across supported google-genai response shapes."""
    text_value = getattr(response, "text", None)
    if text_value:
        return str(text_value)
    candidates = getattr(response, "candidates", None) or []
    parts = getattr(candidates[0].content, "parts", []) if candidates else []
    return "".join(str(getattr(part, "text", "")) for part in parts).strip()


async def _generate_with_gemini(prompt: str) -> str:
    """Generate grounded content with Gemini through the official SDK."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
                response_mime_type="application/json",
            ),
        )
        generated_text = _extract_text(response)
        if not generated_text:
            raise RuntimeError("Gemini returned an empty response")
        return generated_text
    finally:
        close_method = getattr(client, "close", None)
        if close_method is not None:
            close_method()


async def generate_infringement_report(
    user_draft: str,
    top_patents: list[dict[str, Any]],
) -> str:
    """Generate a grounded infringement report using Gemini."""
    if not user_draft.strip():
        raise ValueError("user_draft must be a non-empty string")
    if not top_patents:
        raise ValueError("At least one retrieved patent is required")

    context = format_retrieved_context(top_patents)
    prompt = build_user_prompt(user_draft=user_draft, context=context)

    try:
        report = await _generate_with_gemini(prompt)
        logger.info("Generated infringement report with Gemini")
        return report
    except Exception as gemini_error:
        logger.error("Gemini report generation failed: %s", gemini_error)
        raise RuntimeError(
            "Gemini report generation failed. Check GEMINI_API_KEY and GEMINI_MODEL."
        ) from gemini_error


def parse_report_json(report: str) -> dict[str, Any]:
    """Validate that an LLM response is JSON while preserving its raw text."""
    cleaned_report = report.strip()
    if cleaned_report.startswith("```"):
        lines = cleaned_report.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned_report = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned_report)
    except json.JSONDecodeError:
        object_start = cleaned_report.find("{")
        object_end = cleaned_report.rfind("}")
        if object_start >= 0 and object_end > object_start:
            try:
                parsed = json.loads(cleaned_report[object_start : object_end + 1])
            except json.JSONDecodeError:
                return {"raw_report": report, "structured": False}
        else:
            return {"raw_report": report, "structured": False}
    if not isinstance(parsed, dict):
        return {"raw_report": report, "structured": False}
    return {"raw_report": report, "structured": True, "report": parsed}
