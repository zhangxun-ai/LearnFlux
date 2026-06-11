"""Live LLM check for the flywheel analyzer (uses the real configured model).

Marked ``integration``: it makes a real LLM call via the same coordinator the app
uses, proving the configured key + model path works end-to-end for analysis.
Run explicitly:  pytest tests/integration/test_flywheel_llm_live.py -m integration -s
"""
from pathlib import Path

import pytest

from src.video_transcript_api.utils.logging import load_config
from src.video_transcript_api.llm import LLMCoordinator, set_default_config
from src.video_transcript_api.flywheel.analyzer import ContentAnalyzer
from src.video_transcript_api.flywheel.prompts import VIDEO_SYSTEM_PROMPT, ARTICLE_SYSTEM_PROMPT
from src.video_transcript_api.flywheel.models import MediaType

VIDEO_TRANSCRIPT = (
    "大家好，今天不讲废话，直接说一个我自己验证过、一个月涨粉一万的方法。"
    "很多人一上来就介绍自己，结果三秒就被划走了。你要做的是第一句话就抛一个反常识的结论，"
    "比如别再花钱买课了。中间每隔十几秒给一个新信息或者一个反转，让人舍不得走。"
    "最后一定要引导，比如想要清单的评论区扣一。"
)


@pytest.mark.integration
def test_real_llm_analyzes_video_sample():
    config = load_config()
    set_default_config(config)  # initialize llm-compat SyncLLMClient, as the app does at startup
    coordinator = LLMCoordinator(
        config_dict=config,
        cache_dir=config.get("storage", {}).get("cache_dir", "./data/cache"),
    )
    analyzer = ContentAnalyzer(
        coordinator.llm_client,
        coordinator.config.summary_model,
        getattr(coordinator.config, "summary_reasoning_effort", None),
    )

    out = analyzer.analyze(
        MediaType.VIDEO,
        "一个月涨粉一万的方法",
        VIDEO_TRANSCRIPT,
        {"like_count": 12000, "collect_count": 4200, "comment_count": 890},
        VIDEO_SYSTEM_PROMPT,
    )

    assert out.markdown
    assert "##" in out.markdown

    inspect = Path("data/flywheel/_live_sample.md")
    inspect.parent.mkdir(parents=True, exist_ok=True)
    inspect.write_text(out.markdown, encoding="utf-8")
    print(f"[live-llm] model={analyzer.model} ok, "
          f"output_chars={len(out.markdown)}, headings={out.markdown.count('##')}")
