from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_transcript_template_has_source_translation_and_bilingual_switches():
    template = (PROJECT_ROOT / "src/web/templates/transcript.html").read_text(encoding="utf-8")

    assert "英文原文" in template
    assert "中文译文" in template
    assert "双语" in template
    assert "source_transcript" in template
    assert "zh_translation" in template


def test_processing_template_exposes_cloud_quote_actions():
    template = (PROJECT_ROOT / "src/web/templates/processing.html").read_text(
        encoding="utf-8"
    )

    assert 'task_status != "awaiting_cloud_confirmation"' in template
    assert 'progress.stage === "awaiting_cloud_confirmation"' in template
    assert "确认云端转录" in template
    assert "cloud-use-local" in template
    assert "cloud-refresh" in template
    assert 'data-quote-token="{{ quote.quote_token }}"' not in template


def test_processing_template_renders_server_quote_actions():
    templates = PROJECT_ROOT / "src/web/templates"
    rendered = Environment(loader=FileSystemLoader(templates)).get_template(
        "processing.html"
    ).render(
        task_status="awaiting_cloud_confirmation",
        task_id="synthetic-task",
        view_token="synthetic-view",
        progress={
            "evidence": {
                "cloud_quote": {
                    "quote_token": "synthetic-quote",
                    "duration_seconds": "15.01",
                    "billable_seconds": 16,
                    "max_cost_cny": "0.00352",
                }
            }
        },
    )

    assert "正在从认证任务接口读取云端报价" in rendered
    assert "synthetic-quote" not in rendered


def test_bilingual_switch_is_only_rendered_for_english_source():
    environment = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "src/web/templates")
    )
    template = environment.get_template("transcript.html")
    common = {
        "status": "success",
        "source_transcript": "Source text",
        "zh_translation": "中文译文",
        "transcript": "Source text",
    }

    english = template.render(**common, source_language="en-US")
    chinese = template.render(**common, source_language="zh-CN")

    assert 'data-bilingual-mode="translation"' in english
    assert 'data-bilingual-mode="translation"' not in chinese


def test_result_status_shows_zero_when_remote_asr_was_not_called():
    template = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "src/web/templates")
    ).get_template("transcript.html")

    rendered = template.render(
        status="success",
        stats={"calibration_stats": None, "original_length": 100},
        asr_usage={"label": "云端 ASR 未调用（¥0）", "detail": "本次未产生云端 ASR 用量"},
    )

    assert "云端 ASR 未调用（¥0）" in rendered


def test_asr_usage_display_prefers_calculated_cost_over_quote_ceiling():
    from video_transcript_api.api.routes.views import _build_asr_usage_display

    display = _build_asr_usage_display(
        SimpleNamespace(
            billed_cost=None,
            calculated_cost="0.00044",
            estimated_cost="0.00066",
            currency="CNY",
        )
    )

    assert display["label"] == "云端 ASR 费用约 ¥0.00044"
    assert display["detail"] == "按云端返回用量计算；最终以供应商账单为准"


def test_result_page_does_not_render_legacy_longcut_action():
    template = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "src/web/templates")
    ).get_template("transcript.html")

    rendered = template.render(
        status="success",
        longcut_action={"url": "/legacy-longcut", "label": "用 LongCut 深度学习"},
    )

    assert "用 LongCut 深度学习" not in rendered
    assert "/legacy-longcut" not in rendered
