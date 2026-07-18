"""Unit tests for Xiaohongshu draft generation from flywheel analysis."""
from types import SimpleNamespace

import pytest

from src.video_transcript_api.flywheel.draft_generator import DraftGenerator
from src.video_transcript_api.flywheel.models import (
    Analysis,
    AnalysisStatus,
    Blogger,
    Content,
    MediaType,
)
from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.repositories import (
    SqliteAnalysisCostRepository,
    SqliteAnalysisRepository,
    SqliteBloggerRepository,
    SqliteContentRepository,
    SqlitePromptTemplateRepository,
)


class FakeLLM:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


SAMPLE_DRAFT = """## 标题候选
1. 普通人做决策，先别急着找答案
2. 一个让你少走弯路的判断方法
3. 我终于知道高手为什么不纠结了

## 封面钩子
做决定前，先问自己一个问题。

## 正文
最近我发现一个特别有用的决策方法。

## 互动引导
你最近最纠结的选择是什么？

## 话题标签
#小红书成长 #决策方法 #个人成长

## 创作说明
复用了原帖的问题前置结构，没有复用原文表达。
"""


@pytest.mark.unit
def test_draft_generator_uses_deepseek_v4_pro_high_and_returns_markdown():
    llm = FakeLLM(SAMPLE_DRAFT)
    generator = DraftGenerator(llm_client=llm, model="deepseek-v4-pro", reasoning_effort="high")

    result = generator.generate(
        title="分享一个做好决策的方法",
        author="加肯",
        media_type=MediaType.ARTICLE,
        stats={"like_count": 1234, "collect_count": 88, "comment_count": 12},
        source_text="原帖正文",
        analysis_result={
            "sections": [{"title": "01 内容定位", "body": "写给容易纠结的人。"}],
            "one_thing": "把问题放在第一句。",
        },
    )

    assert result["model"] == "deepseek-v4-pro"
    assert result["reasoning_effort"] == "high"
    assert "普通人做决策" in result["markdown"]
    assert "## 正文" in result["markdown"]
    assert llm.calls[0]["model"] == "deepseek-v4-pro"
    assert llm.calls[0]["reasoning_effort"] == "high"
    assert llm.calls[0]["task_type"] == "flywheel_xhs_draft"
    assert "不要抄袭原文" in llm.calls[0]["system_prompt"]
    assert "分享一个做好决策的方法" in llm.calls[0]["user_prompt"]


@pytest.mark.unit
def test_draft_prompt_locks_original_topic_when_analysis_contains_template_examples():
    llm = FakeLLM(SAMPLE_DRAFT)
    generator = DraftGenerator(llm_client=llm, model="deepseek-v4-pro", reasoning_effort="high")

    generator.generate(
        title="韩红站台被骂背后的商业大洗牌",
        author="屠龙的胭脂井",
        media_type=MediaType.VIDEO,
        stats={"like_count": 394, "collect_count": 0, "comment_count": 0},
        source_text="韩红老师那个走个面事，你不知道吗？",
        analysis_result={
            "sections": [
                {
                    "title": "10 可复制模板",
                    "body": "例：董明珠直播翻车背后的流量逻辑变了",
                }
            ],
            "one_thing": "用有争议的热点事件引出商业认知。",
        },
    )

    prompt = llm.calls[0]["user_prompt"]
    assert "新帖必须围绕原始对标内容的同一核心议题" in prompt
    assert "韩红站台被骂背后的商业大洗牌" in prompt
    assert "不得把拆解里的模板示例" in prompt


@pytest.fixture
def flywheel_env(tmp_path):
    db = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    blogger_repo = SqliteBloggerRepository(db)
    content_repo = SqliteContentRepository(db)
    analysis_repo = SqliteAnalysisRepository(db)
    prompt_repo = SqlitePromptTemplateRepository(db)
    cost_repo = SqliteAnalysisCostRepository(db)
    blogger = blogger_repo.upsert(
        Blogger(id=None, platform="xiaohongshu", platform_user_id="u1", handle="加肯")
    )
    content = content_repo.upsert(
        Content(
            id=None,
            blogger_id=blogger.id,
            platform="xiaohongshu",
            platform_item_id="n1",
            media_type=MediaType.ARTICLE,
            title="分享一个做好决策的方法",
            original_url="https://www.xiaohongshu.com/explore/n1",
            like_count=1234,
            collect_count=88,
            comment_count=12,
        )
    )
    analysis = analysis_repo.create(
        Analysis(
            id=None,
            content_id=content.id,
            media_type=MediaType.ARTICLE,
            status=AnalysisStatus.SUCCESS,
            result_json={
                "sections": [{"title": "01 内容定位", "body": "写给容易纠结的人。"}],
                "one_thing": "把问题放在第一句。",
                "source_text": "原帖正文",
            },
            model="deepseek-v4-flash",
        )
    )
    content_repo.set_analysis_status(content.id, AnalysisStatus.SUCCESS, analysis.id)
    yield SimpleNamespace(
        db=db,
        repos={
            "db": db,
            "blogger": blogger_repo,
            "content": content_repo,
            "analysis": analysis_repo,
            "cost": cost_repo,
            "prompt": prompt_repo,
        },
        content=content,
    )
    db.close()


@pytest.mark.unit
def test_generate_draft_requires_successful_analysis(flywheel_env, monkeypatch):
    from src.video_transcript_api.api.services import flywheel_service

    monkeypatch.setattr(flywheel_service, "_repos", flywheel_env.repos)
    flywheel_env.repos["content"].set_analysis_status(
        flywheel_env.content.id, AnalysisStatus.FAILED, None
    )

    with pytest.raises(ValueError, match="解析成功"):
        flywheel_service.generate_draft(
            flywheel_env.content.id,
            DraftGenerator(FakeLLM(SAMPLE_DRAFT), model="deepseek-v4-pro", reasoning_effort="high"),
        )


@pytest.mark.unit
def test_generate_draft_returns_content_context(flywheel_env, monkeypatch):
    from src.video_transcript_api.api.services import flywheel_service

    llm = FakeLLM(SAMPLE_DRAFT)
    monkeypatch.setattr(flywheel_service, "_repos", flywheel_env.repos)

    result = flywheel_service.generate_draft(
        flywheel_env.content.id,
        DraftGenerator(llm, model="deepseek-v4-pro", reasoning_effort="high"),
    )

    assert result["ok"] is True
    assert result["content_id"] == flywheel_env.content.id
    assert result["source_title"] == "分享一个做好决策的方法"
    assert result["model"] == "deepseek-v4-pro"
    assert "## 标题候选" in result["markdown"]
