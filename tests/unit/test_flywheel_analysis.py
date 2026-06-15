"""Unit tests for Phase 3: prompts, analyzer, repos, analysis status machine + cost."""
from types import SimpleNamespace

import pytest

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import (
    Blogger, Content, MediaType, AnalysisStatus,
)
from src.video_transcript_api.flywheel.repositories import (
    SqliteBloggerRepository, SqliteContentRepository, SqliteAnalysisRepository,
    SqliteAnalysisCostRepository, SqlitePromptTemplateRepository,
)
from src.video_transcript_api.flywheel.prompts import (
    DEFAULT_PROMPTS, parse_sections, VIDEO_SYSTEM_PROMPT,
)
from src.video_transcript_api.flywheel.analyzer import ContentAnalyzer, estimate_cost
from src.video_transcript_api.flywheel.analysis_service import run_analysis


SAMPLE_MD = (
    "## 01 内容定位\n写给副业新手，解决看不懂投资主线的问题。\n\n"
    "## 02 对标价值判断\n可学的是把复杂概念讲成生活比喻。\n\n"
    "## 12 下一条怎么插接\n把重点放第一句。"
)


class FakeLLM:
    def __init__(self, text=None, raise_exc=None):
        self._text, self._raise = text, raise_exc

    def call(self, **kwargs):
        if self._raise:
            raise self._raise
        return SimpleNamespace(text=self._text, structured_output=None)


@pytest.fixture
def env(tmp_path):
    db = FlywheelDB(db_path=str(tmp_path / "f.db"))
    brepo = SqliteBloggerRepository(db)
    crepo = SqliteContentRepository(db)
    arepo = SqliteAnalysisRepository(db)
    costrepo = SqliteAnalysisCostRepository(db)
    prepo = SqlitePromptTemplateRepository(db)
    b = brepo.upsert(Blogger(id=None, platform="xiaohongshu", platform_user_id="u1", handle="@k"))
    c = crepo.upsert(Content(id=None, blogger_id=b.id, platform="xiaohongshu",
                             platform_item_id="n1", media_type=MediaType.VIDEO,
                             title="标题", original_url="https://x/n1", like_count=1200))
    yield SimpleNamespace(crepo=crepo, arepo=arepo, costrepo=costrepo, prepo=prepo, content=c)
    db.close()


# --- prompts ---

@pytest.mark.unit
def test_parse_sections_splits_and_finds_one_thing():
    parsed = parse_sections(SAMPLE_MD)
    assert [s["title"] for s in parsed["sections"]] == [
        "01 内容定位", "02 对标价值判断", "12 下一条怎么插接"]
    assert parsed["one_thing"] == "把重点放第一句。"


@pytest.mark.unit
def test_default_video_prompt_is_benchmark_teardown_prompt():
    required = [
        "对标插接拆解",
        "原文证据",
        "评分标准",
        "可复制模板",
        "不可复制部分",
        "下一条怎么插接",
        "输出前自查",
    ]
    for phrase in required:
        assert phrase in VIDEO_SYSTEM_PROMPT


@pytest.mark.unit
def test_prompt_repo_seed_versioning_and_legacy_upgrade(env):
    legacy_video = "你是爆款短视频拆解教练，说人话、不用术语。"
    env.prepo.upsert(MediaType.VIDEO, legacy_video)
    upgraded = env.prepo.upgrade_default_if_legacy(
        MediaType.VIDEO,
        VIDEO_SYSTEM_PROMPT,
        legacy_bodies=(legacy_video,),
    )
    assert upgraded.body == VIDEO_SYSTEM_PROMPT
    assert upgraded.version == 2


@pytest.mark.unit
def test_prompt_repo_seed_and_versioning(env):
    env.prepo.seed_defaults(DEFAULT_PROMPTS)
    active = env.prepo.get_active(MediaType.VIDEO)
    assert active.version == 1 and active.body == VIDEO_SYSTEM_PROMPT
    updated = env.prepo.upsert(MediaType.VIDEO, "我的新规则")
    assert updated.version == 2
    assert env.prepo.get_active(MediaType.VIDEO).body == "我的新规则"
    versions = env.prepo.list_versions(MediaType.VIDEO)
    assert [p.version for p in versions] == [2, 1]


@pytest.mark.unit
def test_estimate_cost_is_positive():
    in_tok, out_tok, cost = estimate_cost(1700, 850)
    assert in_tok == 1000 and out_tok == 500 and cost > 0


# --- analyzer ---

@pytest.mark.unit
def test_analyzer_returns_markdown_and_char_counts():
    a = ContentAnalyzer(FakeLLM(text=SAMPLE_MD), model="m")
    out = a.analyze(MediaType.VIDEO, "标题", "转写文字", {"like_count": 10}, "SYS")
    assert out.markdown == SAMPLE_MD
    assert out.in_chars > 0 and out.out_chars == len(SAMPLE_MD)


@pytest.mark.unit
def test_analyzer_rejects_empty_llm_output():
    a = ContentAnalyzer(FakeLLM(text="   "), model="m")
    with pytest.raises(ValueError):
        a.analyze(MediaType.VIDEO, "t", "x", {}, "SYS")


# --- status machine + cost ---

@pytest.mark.unit
def test_run_analysis_success_persists_and_costs(env):
    env.prepo.seed_defaults(DEFAULT_PROMPTS)
    analysis = run_analysis(
        env.content, "转写文字",
        analyzer=ContentAnalyzer(FakeLLM(text=SAMPLE_MD), model="gpt-x"),
        analysis_repo=env.arepo, cost_repo=env.costrepo,
        content_repo=env.crepo, prompt_repo=env.prepo,
    )
    assert analysis.status is AnalysisStatus.SUCCESS
    assert analysis.result_json["source_text"] == "转写文字"
    assert analysis.result_json["one_thing"] == "把重点放第一句。"
    assert env.crepo.get(env.content.id).analysis_status is AnalysisStatus.SUCCESS
    assert env.crepo.get(env.content.id).latest_analysis_id == analysis.id
    assert env.costrepo.total() > 0
    assert env.costrepo.total_by_blogger()[env.content.blogger_id] > 0


@pytest.mark.unit
def test_run_analysis_failure_marks_failed_no_cost(env):
    env.prepo.seed_defaults(DEFAULT_PROMPTS)
    analysis = run_analysis(
        env.content, "转写文字",
        analyzer=ContentAnalyzer(FakeLLM(raise_exc=RuntimeError("boom")), model="gpt-x"),
        analysis_repo=env.arepo, cost_repo=env.costrepo,
        content_repo=env.crepo, prompt_repo=env.prepo,
    )
    assert analysis.status is AnalysisStatus.FAILED
    assert "boom" in analysis.error_message
    assert env.crepo.get(env.content.id).analysis_status is AnalysisStatus.FAILED
    assert env.costrepo.total() == 0
