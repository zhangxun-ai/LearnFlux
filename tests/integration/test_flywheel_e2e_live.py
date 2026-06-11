"""End-to-end live check on real Xiaohongshu URLs (provided by the user).

Article path runs fully (fetch note body -> real LLM -> breakdown). Marked
integration; makes real TikHub + LLM calls. Results are written to
data/flywheel/ for manual inspection (test logs stay English).
"""
from pathlib import Path

import pytest

from src.video_transcript_api.utils.logging import load_config
from src.video_transcript_api.llm import LLMCoordinator, set_default_config
from src.video_transcript_api.flywheel.analyzer import ContentAnalyzer
from src.video_transcript_api.flywheel.prompts import (
    VIDEO_SYSTEM_PROMPT, ARTICLE_SYSTEM_PROMPT,
)
from src.video_transcript_api.flywheel.models import MediaType
from src.video_transcript_api.flywheel.text_acquisition import fetch_note_detail, acquire_text

ARTICLE_URL = ("https://www.xiaohongshu.com/discovery/item/69e72660000000001f0055b6"
               "?source=webshare&xhsshare=pc_web"
               "&xsec_token=ABhx8az_Lx2_9_ZyJqqZB8GgDp8g5pZsNIs_jdU-0rRSA=&xsec_source=pc_share")
VIDEO_URL = ("https://www.xiaohongshu.com/discovery/item/6a1ceb8a00000000080306aa"
             "?source=webshare&xhsshare=pc_web"
             "&xsec_token=AB6w1KLme-ykqXzgvgySIufM_L-yfr8eomVpufWJ0fqk8=&xsec_source=pc_share")


def _build_analyzer() -> ContentAnalyzer:
    config = load_config()
    set_default_config(config)
    coord = LLMCoordinator(config_dict=config,
                           cache_dir=config.get("storage", {}).get("cache_dir", "./data/cache"))
    return ContentAnalyzer(coord.llm_client, coord.config.summary_model,
                           getattr(coord.config, "summary_reasoning_effort", None))


@pytest.mark.integration
def test_article_end_to_end():
    detail = fetch_note_detail(ARTICLE_URL)
    print(f"[e2e-article] fetched note_id={detail.note_id} type={detail.media_type.value} "
          f"title_len={len(detail.title)} body_len={len(detail.body_text)} "
          f"likes={detail.like_count}")
    assert detail.media_type is MediaType.ARTICLE
    assert detail.body_text  # got real body text

    prompt = ARTICLE_SYSTEM_PROMPT if detail.media_type is MediaType.ARTICLE else VIDEO_SYSTEM_PROMPT
    analyzer = _build_analyzer()
    out = analyzer.analyze(
        detail.media_type, detail.title, detail.body_text,
        {"like_count": detail.like_count, "collect_count": detail.collect_count,
         "comment_count": detail.comment_count},
        prompt,
    )
    assert "##" in out.markdown
    Path("data/flywheel/_e2e_article.md").write_text(
        f"# {detail.title}\n\n{out.markdown}", encoding="utf-8")
    print(f"[e2e-article] analyzed ok, output_chars={len(out.markdown)}, "
          f"headings={out.markdown.count('##')}")


@pytest.mark.integration
def test_video_end_to_end():
    detail, transcript = acquire_text(VIDEO_URL)  # fetch + download + local transcribe
    print(f"[e2e-video] note_id={detail.note_id} type={detail.media_type.value} "
          f"transcript_chars={len(transcript)}")
    assert detail.media_type is MediaType.VIDEO
    assert transcript

    analyzer = _build_analyzer()
    out = analyzer.analyze(
        detail.media_type, detail.title, transcript,
        {"like_count": detail.like_count, "collect_count": detail.collect_count,
         "comment_count": detail.comment_count},
        VIDEO_SYSTEM_PROMPT,
    )
    assert "##" in out.markdown
    Path("data/flywheel/_e2e_video.md").write_text(
        f"# {detail.title}\n\n## 转写片段\n{transcript[:300]}...\n\n{out.markdown}",
        encoding="utf-8")
    print(f"[e2e-video] analyzed ok, output_chars={len(out.markdown)}, "
          f"headings={out.markdown.count('##')}")
