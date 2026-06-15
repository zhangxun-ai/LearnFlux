"""Orchestrate one content analysis: status machine + persistence + cost.

Depends only on repository Protocols + an analyzer (all injectable). Drives the
``pending -> processing -> success/failed`` lifecycle, stores the structured
result, and records an estimated cost ledger entry. Never raises on LLM failure
— it records ``failed`` so the UI can show a retry.
"""
from __future__ import annotations

from ..utils.logging import setup_logger
from .analyzer import ContentAnalyzer, estimate_cost
from .models import Analysis, AnalysisCost, AnalysisStatus, Content
from .prompts import default_prompt, parse_sections
from .repositories import (
    AnalysisCostRepository, AnalysisRepository, ContentRepository,
    PromptTemplateRepository,
)

logger = setup_logger("flywheel_analysis_service")


def run_analysis(
    content: Content,
    text: str,
    *,
    analyzer: ContentAnalyzer,
    analysis_repo: AnalysisRepository,
    cost_repo: AnalysisCostRepository,
    content_repo: ContentRepository,
    prompt_repo: PromptTemplateRepository,
) -> Analysis:
    """Analyze ``content`` (with already-acquired ``text``) and persist everything."""
    content_repo.set_analysis_status(content.id, AnalysisStatus.PROCESSING)

    active = prompt_repo.get_active(content.media_type)
    system_prompt = active.body if active else default_prompt(content.media_type)
    prompt_version = active.version if active else None
    stats = {"like_count": content.like_count, "collect_count": content.collect_count,
             "comment_count": content.comment_count}

    try:
        out = analyzer.analyze(content.media_type, content.title, text, stats, system_prompt)
    except Exception as exc:  # noqa: BLE001 - record failure, don't crash the request
        logger.warning(f"analysis failed: content={content.id}, error={exc}")
        failed = analysis_repo.create(Analysis(
            id=None, content_id=content.id, media_type=content.media_type,
            status=AnalysisStatus.FAILED, result_json={}, error_message=str(exc),
            prompt_version=prompt_version, model=analyzer.model,
        ))
        content_repo.set_analysis_status(content.id, AnalysisStatus.FAILED, failed.id)
        return failed

    result_json = parse_sections(out.markdown)
    result_json["source_text"] = text
    result_json["source_label"] = "视频转写文字" if content.media_type.value == "video" else "图文正文"

    analysis = analysis_repo.create(Analysis(
        id=None, content_id=content.id, media_type=content.media_type,
        status=AnalysisStatus.SUCCESS, result_json=result_json,
        prompt_version=prompt_version, model=analyzer.model,
    ))
    in_tok, out_tok, cost = estimate_cost(out.in_chars, out.out_chars)
    cost_repo.add(AnalysisCost(
        id=None, analysis_id=analysis.id, content_id=content.id,
        blogger_id=content.blogger_id, in_tokens=in_tok, out_tokens=out_tok, total_cost=cost,
    ))
    content_repo.set_analysis_status(content.id, AnalysisStatus.SUCCESS, analysis.id)
    logger.info(f"analysis ok: content={content.id}, cost≈{cost} CNY")
    return analysis
