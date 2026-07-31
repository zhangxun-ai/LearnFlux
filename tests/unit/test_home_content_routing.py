"""Behavior tests for source detection and intent routing on the home workbench."""

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_JS = PROJECT_ROOT / "src/web/static/js/app.js"
INDEX_HTML = PROJECT_ROOT / "src/web/static/index.html"


def _run_node(source: str) -> object:
    node = shutil.which("node")
    assert node, "Node.js is required for workbench behavior tests"
    result = subprocess.run(
        [node, "-e", source],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _url_extractor_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const URL_PATTERNS")
    end = source.index("\n/**\n * API调用管理类", start)
    return source[start:end]


def _classification_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function classifySource")
    end = source.index("\n/** 历史状态徽章信息 */", start)
    return source[start:end]


def _history_routing_source() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    history_start = source.index("const LOCAL_MEDIA_HISTORY_EXTENSIONS")
    history_end = source.index("\nfunction buildHistoryCard", history_start)
    audit_start = source.index("function historyTypeFromAuditItem(item)")
    audit_end = source.index("\nfunction mergeMarkedHistoryItems", audit_start)
    return (
        _classification_source()
        + source[history_start:history_end]
        + source[audit_start:audit_end]
    )


def test_official_account_url_is_not_duplicated_as_embedded_qq_url():
    source = _url_extractor_source()
    result = _run_node(
        source
        + """
const urls = URLExtractor.extractURLs(
    'Read https://mp.weixin.qq.com/s/r5aDx2ntV9E1QWM3oHe3kw now'
);
process.stdout.write(JSON.stringify(urls));
"""
    )

    assert result == [
        "https://mp.weixin.qq.com/s/r5aDx2ntV9E1QWM3oHe3kw",
    ]


def test_wechat_sources_are_classified_without_selecting_analysis_intent():
    source = _classification_source()
    result = _run_node(
        source
        + """
const result = {
    articleSource: classifySource('https://mp.weixin.qq.com/s/article-token'),
    channelSource: classifySource('https://weixin.qq.com/sph/AUqdQVIvFa'),
    articlePresentation: classifyContent(
        'https://mp.weixin.qq.com/s/article-token',
        'deep_learning'
    ),
};
process.stdout.write(JSON.stringify(result));
"""
    )

    assert result["articleSource"]["sourceType"] == "wechat_mp_article"
    assert result["channelSource"]["sourceType"] == "wechat_channels_video"
    assert result["articlePresentation"]["type"] == "article"
    assert result["articlePresentation"]["analysisIntent"] == "deep_learning"


def test_all_sources_keep_the_entry_analysis_intent():
    source = _classification_source()
    result = _run_node(
        source
        + """
const urls = [
    'https://mp.weixin.qq.com/s/article-token',
    'https://www.xiaohongshu.com/explore/note-token',
    'https://weixin.qq.com/sph/AUqdQVIvFa',
    'https://www.douyin.com/video/1234567890',
    'https://www.youtube.com/watch?v=abc123',
    'https://x.com/leoxbtt/status/2082108948505674112/video/1?s=46',
    'https://example.com/media/lesson.mp4'
];
const result = urls.map((url) => ({
    url,
    source: classifySource(url),
    deep: classifyContent(url, 'deep_learning'),
    post: classifyContent(url, 'post_insight')
}));
process.stdout.write(JSON.stringify(result));
"""
    )

    assert all(item["deep"]["analysisIntent"] == "deep_learning" for item in result)
    assert all(item["deep"]["historyType"] != "post" for item in result)
    assert all(item["post"]["analysisIntent"] == "post_insight" for item in result)
    assert all(item["post"]["historyType"] == "post" for item in result)
    assert result[5]["source"]["sourceType"] == "social_post"


def test_history_navigation_uses_saved_intent_not_the_source_domain():
    source = _history_routing_source()
    result = _run_node(
        source
        + """
const xUrl = 'https://x.com/leoxbtt/status/2082108948505674112/video/1?s=46';
const result = {
    deepType: histTypeOf({
        url: xUrl,
        analysis_intent: 'deep_learning',
        view_token: 'view-x'
    }),
    postType: histTypeOf({
        url: xUrl,
        analysis_intent: 'post_insight',
        result_id: 'post-x'
    }),
    legacyAuditType: historyTypeFromAuditItem({
        video_url: xUrl,
        platform: 'twitter',
        view_token: 'view-legacy'
    }),
    deepRetry: historyActionHref({
        url: xUrl,
        status: 'failed',
        analysis_intent: 'deep_learning'
    }),
    postRetry: historyActionHref({
        url: xUrl,
        status: 'failed',
        analysis_intent: 'post_insight'
    })
};
process.stdout.write(JSON.stringify(result));
"""
    )

    assert result == {
        "deepType": "video",
        "postType": "post",
        "legacyAuditType": "video",
        "deepRetry": "/add_task_by_web",
        "postRetry": (
            "/post?url=https%3A%2F%2Fx.com%2Fleoxbtt%2Fstatus%2F"
            "2082108948505674112%2Fvideo%2F1%3Fs%3D46"
        ),
    }


def test_single_study_keeps_article_intent_and_hides_transcription_options():
    html = INDEX_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "src/web/static/css/workbench.css").read_text(
        encoding="utf-8"
    )
    submit_start = source.index("async function submitTranscription(event)")
    submit_end = source.index("\n/**\n * 页面初始化", submit_start)
    submit_source = source[submit_start:submit_end]

    assert 'id="video-options"' in html
    assert "#video-options[hidden]" in css
    assert "analysis_intent: analysisIntent" in source
    assert "source_type: sourceType" in source
    assert "detected.type === 'post'" not in submit_source
    assert "切换到帖子洞察" in source
    assert "将调用 TikHub 获取正文并调用 AI" in source
    assert "不会自动抓取评论" in source
    assert 'document.getElementById("include-comments")' not in html
    assert "const includeComments = false;" in submit_source
