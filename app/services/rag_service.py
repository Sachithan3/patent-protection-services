"""LLM orchestration for grounded patent infringement reports."""

import asyncio
import json
import logging
import time
from typing import Any, Mapping, Sequence

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.rag_prompt import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

# Full claim sets make the prompt very large (several patents x 20 claims) and
# add tens of seconds of latency without improving the evidence used by the
# report. Keep claim 1 plus the claims that actually matched, then fill with
# further claims only while the per-patent budget allows.
_MAX_SELECTED_CLAIMS = 6
_CLAIM_CHAR_BUDGET = 2600


def _select_claims(patent: Mapping[str, Any]) -> tuple[list[tuple[int, str]], int]:
    """Return the claims worth sending to the LLM and the total claim count."""
    claims = [str(claim) for claim in (patent.get("claims") or [])]
    if not claims:
        return [], 0

    preferred: list[int] = [1]
    for item in patent.get("matched_claims") or []:
        try:
            claim_number = int(item.get("claim_number"))
        except (AttributeError, TypeError, ValueError):
            continue
        if 1 <= claim_number <= len(claims):
            preferred.append(claim_number)

    ordered: list[int] = []
    for claim_number in [*preferred, *range(1, len(claims) + 1)]:
        if claim_number not in ordered:
            ordered.append(claim_number)

    selected: list[tuple[int, str]] = []
    used_chars = 0
    always_include = set(preferred)
    for claim_number in ordered:
        claim_text = claims[claim_number - 1]
        within_budget = used_chars + len(claim_text) <= _CLAIM_CHAR_BUDGET
        if claim_number not in always_include and not within_budget:
            continue
        selected.append((claim_number, claim_text))
        used_chars += len(claim_text)
        if len(selected) >= _MAX_SELECTED_CLAIMS:
            break

    return sorted(selected), len(claims)


def format_retrieved_context(top_patents: Sequence[Mapping[str, Any]]) -> str:
    """Format retrieval results into explicit, claim-numbered legal context."""
    sections: list[str] = []
    for patent in top_patents:
        selected_claims, total_claims = _select_claims(patent)
        claim_lines = "\n".join(
            f"  Claim {claim_number}: {claim_text}"
            for claim_number, claim_text in selected_claims
        )
        selection_note = (
            f"Selected claims: {len(selected_claims)} of {total_claims} "
            "(claim 1 and the strongest matched claims are prioritised). "
            "Omitted claims were not retrieved for this analysis; do not infer "
            "their scope."
            if selected_claims and len(selected_claims) < total_claims
            else "Claims:"
        )
        sections.append(
            "\n".join(
                [
                    f"Patent ID: {patent.get('patent_id', 'UNKNOWN')}",
                    f"Title: {patent.get('title', 'UNKNOWN')}",
                    f"Category: {patent.get('category', 'UNKNOWN')}",
                    f"Abstract: {patent.get('abstract', '')}",
                    f"Retrieval semantic signal: {float(patent.get('cosine_similarity', 0.0)) * 100:.1f}/100",
                    f"Evidence type: {patent.get('evidence_type', 'unknown')}",
                    f"Evidence score: {float(patent.get('claim_overlap_score', 0.0)):.1f}/100",
                    f"Indexed feature coverage: {float(patent.get('feature_coverage', 0.0)):.1f}/100",
                    "Matched claim evidence:",
                    "\n".join(
                        f"  Claim {item.get('claim_number')}: "
                        f"{item.get('score', 0):.1f}/100 (see claim text below)"
                        for item in patent.get("matched_claims", [])
                    ) or "  No claim-level match passed the evidence threshold.",
                    selection_note,
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

    timeout_seconds = settings.gemini_timeout_seconds
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=int(timeout_seconds * 1000),
            retry_options=types.HttpRetryOptions(attempts=2, max_delay=5.0),
        ),
    )
    started = time.monotonic()
    try:
        logger.info(
            "Requesting Gemini report (model=%s, prompt_chars=%d, timeout=%.0fs)",
            settings.gemini_model,
            len(prompt),
            timeout_seconds,
        )
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=settings.llm_temperature,
                    max_output_tokens=settings.llm_max_output_tokens,
                    response_mime_type="application/json",
                ),
            ),
            # The SDK timeout covers a single HTTP attempt; this cap covers
            # retries as well so a stalled request can never hang forever.
            timeout=timeout_seconds + 5,
        )
        generated_text = _extract_text(response)
        if not generated_text:
            raise RuntimeError("Gemini returned an empty response")
        logger.info(
            "Gemini report received in %.1fs (%d chars)",
            time.monotonic() - started,
            len(generated_text),
        )
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
    except TimeoutError as timeout_error:
        logger.error("Gemini report generation timed out: %s", timeout_error)
        raise RuntimeError(
            "Gemini did not respond within "
            f"{get_settings().gemini_timeout_seconds:.0f} seconds. "
            "The report service may be busy; please try again."
        ) from timeout_error
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
