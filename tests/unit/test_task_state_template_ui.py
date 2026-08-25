from pathlib import Path


TEMPLATE_DIR = Path(__file__).parents[2] / "src" / "web" / "templates"
STATIC_DIR = Path(__file__).parents[2] / "src" / "web" / "static"


def test_error_page_exposes_a_single_clear_alert_and_non_inline_reload_action():
    source = (TEMPLATE_DIR / "error.html").read_text(encoding="utf-8")

    assert 'class="error-panel" role="alert"' in source
    assert 'data-reload-page' in source
    assert 'onclick="window.location.reload()"' not in source


def test_processing_page_respects_reduced_motion_and_describes_progress():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert '@media (prefers-reduced-motion: reduce)' in source
    assert 'role="progressbar"' in source
    assert 'aria-valuetext=' in source
    assert 'setAttribute("aria-valuetext"' in source


def test_processing_page_loads_quote_actions_after_polling_enters_confirmation():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert 'id="cloud-quote-actions"' in source
    assert '{% if task_status == "awaiting_cloud_confirmation" %}' not in source
    assert 'progress.stage === "awaiting_cloud_confirmation"' in source
    assert "loadCloudQuoteActions();" in source


def test_processing_page_reports_local_fallback_immediately_after_selection():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert 'action === "cloud-use-local"' in source
    assert "已选择本地免费，正在启动本地转录…" in source


def test_processing_page_disables_cloud_confirmation_after_first_click():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert "let quoteActionPending = false;" in source
    assert "if (quoteActionPending) return;" in source
    assert "button.dataset.action = action;" in source
    assert 'confirmButton.textContent = "已确认";' in source
    assert "confirmButton.disabled = true;" in source
    assert 'document.getElementById("progress-stage").textContent = "云端转录排队中";' in source
    assert "确认已生效，请勿重复操作。" not in source
    assert "云端转录已确认，正在排队" not in source
    assert (
        'quoteActionPending && progress.stage === "awaiting_cloud_confirmation"'
        in source
    )
    assert 'progress.stage !== "awaiting_cloud_confirmation"' in source


def test_processing_page_offers_a_confirmed_cancel_action():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert 'id="cancel-task"' in source
    assert 'data-task-id="{{ task_id }}"' in source
    assert "取消本次解析？" in source
    assert "/cancel" in source
    assert '"canceled"' in source


def test_processing_page_uses_an_accessible_custom_cancel_dialog():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert '<dialog id="cancel-confirm-dialog"' in source
    assert 'aria-labelledby="cancel-confirm-title"' in source
    assert '<form method="dialog"' in source
    assert 'value="confirm"' in source
    assert 'cancelConfirmDialog.showModal();' in source
    assert 'cancelConfirmDialog.addEventListener("close"' in source
    assert "window.confirm(" not in source


def test_processing_page_returns_to_the_previous_page_after_cancellation():
    source = (TEMPLATE_DIR / "processing.html").read_text(encoding="utf-8")

    assert "已取消，正在返回…" in source
    assert "function returnAfterCancellation()" in source
    assert "window.history.back();" in source
    assert 'window.location.assign("/add_task_by_web");' in source
    assert "window.setTimeout(returnAfterCancellation, 700);" in source


def test_transcript_reader_and_export_menu_are_keyboard_accessible():
    template_source = (TEMPLATE_DIR / "transcript.html").read_text(encoding="utf-8")
    reader_source = (STATIC_DIR / "js" / "transcript-visual-reader.js").read_text(
        encoding="utf-8"
    )

    assert 'aria-haspopup="dialog"' in template_source
    assert 'aria-expanded="false"' in template_source
    assert 'role="dialog"' in template_source
    assert 'role="radio"' in template_source
    assert "case 'ArrowRight':" in reader_source
    assert "case 'Home':" in reader_source
