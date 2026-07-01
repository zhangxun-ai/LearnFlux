"""Unit tests for Xiaohongshu share text URL handling."""
from types import SimpleNamespace

import pytest

from src.video_transcript_api.flywheel.db import FlywheelDB
from src.video_transcript_api.flywheel.models import AnalysisStatus, MediaType
from src.video_transcript_api.flywheel.prompts import DEFAULT_PROMPTS
from src.video_transcript_api.flywheel.repositories import (
    SqliteAnalysisCostRepository,
    SqliteAnalysisRepository,
    SqliteBloggerRepository,
    SqliteContentRepository,
    SqlitePromptTemplateRepository,
)
from src.video_transcript_api.flywheel import text_acquisition


SHARE_TEXT = (
    "57 【妈妈再也不用担心我会亏钱啦！ - 昊子商业观察 | 小红书 - 你的生活兴趣社区】 "
    "😆 bORZCNlEPxXOHuD 😆 "
    "https://www.xiaohongshu.com/discovery/item/69e754ba000000001b003e92"
    "?source=webshare&xhsshare=pc_web"
    "&xsec_token=AB3QEOb5z9P0yoHf_sTyqtJjdG8FkMi8sipAXf2xvoS6o="
    "&xsec_source=pc_share"
)
CANONICAL_URL = (
    "https://www.xiaohongshu.com/discovery/item/69e754ba000000001b003e92"
    "?source=webshare&xhsshare=pc_web"
    "&xsec_token=AB3QEOb5z9P0yoHf_sTyqtJjdG8FkMi8sipAXf2xvoS6o="
    "&xsec_source=pc_share"
)
SHORT_SHARE_TEXT = (
    "韩红站台被骂背后的商业大洗牌 最近韩红给冯小刚站台... "
    "http://xhslink.com/o/3NQcpZvI5GG \n"
    "戳进【小红书】看看这篇好文！"
)
SHORT_CANONICAL_URL = (
    "https://www.xiaohongshu.com/discovery/item/6a2fd6d1000000001702f4b6"
    "?xsec_token=tok123"
)


@pytest.mark.unit
def test_normalize_note_url_extracts_url_from_share_text():
    normalize_note_url = getattr(text_acquisition, "normalize_note_url", None)
    assert normalize_note_url is not None
    assert normalize_note_url(SHARE_TEXT) == CANONICAL_URL
    assert normalize_note_url(CANONICAL_URL) == CANONICAL_URL


@pytest.mark.unit
def test_fetch_note_detail_resolves_xhslink_share_text(monkeypatch):
    def fake_resolve(url):
        assert url == "http://xhslink.com/o/3NQcpZvI5GG"
        return SHORT_CANONICAL_URL

    calls = []

    def fake_api_request(endpoint, params):
        calls.append((endpoint, params))
        return {
            "code": 0,
            "data": [{
                "note_list": [{
                    "title": "韩红站台被骂背后的商业大洗牌",
                    "desc": "正文",
                    "type": "normal",
                    "user": {"nickname": "作者"},
                }],
            }],
        }

    monkeypatch.setattr(text_acquisition, "_resolve_short_url", fake_resolve, raising=False)

    detail = text_acquisition.fetch_note_detail(
        SHORT_SHARE_TEXT,
        api_request=fake_api_request,
    )

    assert detail.note_id == "6a2fd6d1000000001702f4b6"
    assert detail.title == "韩红站台被骂背后的商业大洗牌"
    assert calls[0] == (
        "/api/v1/xiaohongshu/web_v3/fetch_note_detail",
        {"note_id": "6a2fd6d1000000001702f4b6", "xsec_token": "tok123"},
    )


@pytest.mark.unit
def test_analyze_url_persists_canonical_url_from_share_text(tmp_path, monkeypatch):
    from src.video_transcript_api.api.services import flywheel_service
    from src.video_transcript_api.flywheel.text_acquisition import NoteDetail

    db = FlywheelDB(db_path=str(tmp_path / "flywheel.db"))
    prompt = SqlitePromptTemplateRepository(db)
    prompt.seed_defaults(DEFAULT_PROMPTS)
    repos = {
        "db": db,
        "blogger": SqliteBloggerRepository(db),
        "content": SqliteContentRepository(db),
        "analysis": SqliteAnalysisRepository(db),
        "cost": SqliteAnalysisCostRepository(db),
        "prompt": prompt,
    }
    monkeypatch.setattr(flywheel_service, "_repos", repos)

    def fake_acquire_text(url):
        assert url == CANONICAL_URL
        return (
            NoteDetail(
                note_id="69e754ba000000001b003e92",
                media_type=MediaType.VIDEO,
                title="妈妈再也不用担心我会亏钱啦！",
                body_text="",
                author="昊子商业观察",
                author_user_id="haoz",
                like_count=6845,
            ),
            "转写文字",
        )

    def fake_run_analysis(*args, **kwargs):
        return SimpleNamespace(
            status=AnalysisStatus.SUCCESS,
            result_json={"sections": [], "one_thing": "", "markdown": "", "source_text": "转写文字"},
            error_message=None,
        )

    monkeypatch.setattr(flywheel_service, "acquire_text", fake_acquire_text)
    monkeypatch.setattr(flywheel_service, "run_analysis", fake_run_analysis)

    result = flywheel_service.analyze_url(SHARE_TEXT, analyzer=object())
    content = repos["content"].get(result["content_id"])

    assert result["original_url"] == CANONICAL_URL
    assert result["source_text"] == "转写文字"
    assert content.original_url == CANONICAL_URL

    db.close()


@pytest.mark.unit
def test_flywheel_analyzer_does_not_reuse_summary_high_reasoning(monkeypatch):
    from src.video_transcript_api.api.routes import flywheel

    coordinator = SimpleNamespace(
        llm_client=object(),
        config=SimpleNamespace(
            summary_model="deepseek-v4-flash",
            summary_reasoning_effort="high",
        ),
    )
    monkeypatch.setattr(flywheel, "get_llm_coordinator", lambda: coordinator)

    analyzer = flywheel._build_analyzer()

    assert analyzer.model == "deepseek-v4-flash"
    assert analyzer.reasoning_effort is None


@pytest.mark.unit
def test_flywheel_page_exposes_prompt_editor():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    html = (project_root / "src/web/templates/flywheel.html").read_text(encoding="utf-8")

    assert "prompt-media-type" in html
    assert "prompt-body" in html
    assert "/api/flywheel/prompts" in html
    assert "恢复默认提示词" in html
    assert "result-toc" in html
    assert "source-text" in html
    assert "基于拆解生成新帖" in html
    assert "/api/flywheel/content/'+contentId+'/draft" in html
    assert "复制全文" in html


@pytest.mark.unit
def test_workbench_keeps_xiaohongshu_in_deep_learning_flow():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    js = (project_root / "src/web/static/js/app.js").read_text(encoding="utf-8")

    assert "platform: 'xiaohongshu'" in js
    assert "label: '小红书内容'" in js
    assert "视频转录 / 图文深度学习" in js
    assert "label: '小红书视频'" not in js
    assert "type: 'flywheel'" not in js
    assert "window.location.href = '/flywheel?url='" not in js


@pytest.mark.unit
def test_frontend_module_names_keep_workflows_separate():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    nav = (project_root / "src/web/static/js/site-nav.js").read_text(encoding="utf-8")
    workbench = (project_root / "src/web/static/index.html").read_text(encoding="utf-8")
    collections = (project_root / "src/web/static/collections.html").read_text(encoding="utf-8")
    flywheel = (project_root / "src/web/templates/flywheel.html").read_text(encoding="utf-8")

    assert "单篇深度学习" in nav
    assert "系列深度学习" in nav
    assert "帖子洞察" in nav
    assert "IP 对标" in nav
    assert "历史" in nav
    assert "/static/history.html" in nav
    assert "单个解析" not in nav
    assert "学做小红书" not in nav

    assert "视频/文档深度学习" in workbench
    assert 'id="share-content"' in workbench
    assert 'name="deep-learning-source-content"' in workbench
    assert 'id="bearer-token"' in workbench
    assert 'type="password"' not in workbench
    assert 'autocomplete="new-password"' in workbench
    assert "系列深度学习" in collections
    assert "IP 对标工作台" in flywheel
    assert "学做小红书" not in flywheel
