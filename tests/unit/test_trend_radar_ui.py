from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src/web/static"


def test_trend_radar_static_page_exposes_core_ui_contract():
    html = (STATIC_DIR / "trend-radar.html").read_text(encoding="utf-8")

    assert 'id="trend-radar-app"' in html
    assert "趋势机会雷达" in html
    assert "AI 社会需求趋势雷达" in html
    assert "五层产业栈" in html
    assert "需求映射" in html
    assert "今日策展结论" in html
    assert "能源" in html
    assert "芯片 / 计算" in html
    assert "基础设施 / AI 工厂" in html
    assert "模型" in html
    assert "应用" in html
    assert "安全需求" in html
    assert "认知需求" in html
    assert "自我实现" in html
    assert 'id="stack-gallery"' in html
    assert 'id="need-gallery"' in html
    assert 'id="curation-list"' in html
    assert 'id="matrix-panel"' in html
    assert "新进入机会期" in html
    assert "过热预警" in html
    assert "单次预算" in html
    assert 'value="2"' in html
    assert "建议 $2" in html
    assert "预算硬限制" not in html
    assert "480 次" not in html
    assert "LLM 终审" not in html
    assert "最近报告" in html
    assert 'id="priority-list"' in html
    assert 'id="watch-list"' in html
    assert 'id="run-status"' in html
    assert 'id="run-budget"' in html
    assert 'id="budget-hint"' in html
    assert 'id="report-history-list"' in html
    assert 'data-stage-filter="opportunity"' in html
    assert 'href="/static/css/trend-radar.css?v=7"' in html
    assert 'src="/static/js/trend-radar.js?v=6"' in html


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


def test_trend_radar_uses_static_app_shell():
    html = (STATIC_DIR / "trend-radar.html").read_text(encoding="utf-8")
    shell_css = (STATIC_DIR / "css/app-shell.css").read_text(encoding="utf-8")

    assert 'class="app-shell has-app-shell product-linear page-trend"' in html
    assert '<aside class="sidebar"' in html
    assert '<main class="main-area"' in html
    assert 'href="/trend-radar"' in html
    assert "趋势雷达" in html
    assert "#site-nav" not in html
    assert "site-nav.js" not in html
    assert "body.app-shell" in shell_css
