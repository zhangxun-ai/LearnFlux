import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src/web/static"


def test_trend_radar_static_page_is_removed():
    assert not (STATIC_DIR / "trend-radar.html").exists()


def test_trend_radar_assets_support_responsive_interaction():
    css = (STATIC_DIR / "css/trend-radar.css").read_text(encoding="utf-8")
    js = (STATIC_DIR / "js/trend-radar.js").read_text(encoding="utf-8")

    assert ".radar-shell" in css
    assert ".dashboard-header" in css
    assert ".summary-strip" in css
    assert ".radar-bento" in css
    assert ".panel" in css
    assert ".gallery-grid" in css
    assert ".need-grid" in css
    assert ".matrix-panel" in css
    assert ".matrix-dot-button" in css
    assert ".decision-panel" in css
    assert ".run-panel" in css
    assert ".evidence-card" in css
    assert ".stack-badge" in css
    assert ".need-badge" in css
    assert ".decision-badge" in css
    assert ".brief-panel" in css
    assert ".brief-list" in css
    assert ".data-quality-panel" in css
    assert ".evidence-head" in css
    assert ".key-fact-list" in css
    assert ".raw-source" in css
    assert ":focus-visible" in css
    assert "@media (max-width: 760px)" in css
    assert "trendRadarData" in js
    assert "stackLayer" in js
    assert "needLayer" in js
    assert "socialNeed" in js
    assert "supplyShift" in js
    assert "counterEvidence" in js
    assert "renderStackGallery" in js
    assert "renderNeedGallery" in js
    assert "renderCurationList" in js
    assert "renderMatrixPanel" in js
    assert "Number(els.budget?.value || 2)" in js
    assert "建议 $2" in js
    assert "TikHub 请求" not in js
    assert "LLM 终审" not in js
    assert "decision-brief-v4" in js
    assert "legacy_report_version" in js
    assert "missing_chinese_preview" in js
    assert "hasRequiredChineseEvidencePreviews" in js
    assert "英文来源尚未生成中文解读" in js
    assert "/api/trend-radar/reports/run" in js
    assert "/api/trend-radar/jobs/" in js
    assert "waitForReportJob" in js
    assert "networkErrorMessage" in js
    assert "无法连接 8000 后端服务" in js
    assert "后台生成中" in js
    assert "/api/trend-radar/reports/latest" in js
    assert "/api/trend-radar/reports?limit=8" in js
    assert "loadReportHistory" in js
    assert "打开原文" in js
    assert "优先核查来源" in js
    assert "displayTitle" in js
    assert "displaySummary" in js
    assert "原始标题" in js
    assert 'aria-label="决策简报"' in js
    assert "topic_mismatch" in js
    assert "renderNoOpportunityState" in js
    assert "renderPriorityBoard" in js
    assert "renderTrendList" in js
    assert "renderTrendDetail" in js
    assert "validationAction" in js
    assert "evidence" in js
    assert "opportunity" in js
    assert "反对者地图" not in js
    assert 'id="business-title"' not in js
    assert "认知扩散矩阵" not in js
    assert "扩散时间线" not in js


def test_trend_radar_is_not_exposed_as_a_product_route():
    navigation = json.loads(
        (PROJECT_ROOT / "src/web/product-navigation.json").read_text(encoding="utf-8")
    )
    app = (PROJECT_ROOT / "src/video_transcript_api/api/app.py").read_text(
        encoding="utf-8"
    )

    assert "trend_radar" not in navigation["items"]
    assert not any(
        item.get("href") == "/trend-radar"
        for item in navigation["items"].values()
    )
    assert "trend_radar.router" not in app
