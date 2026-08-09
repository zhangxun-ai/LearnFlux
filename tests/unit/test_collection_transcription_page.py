"""Static contracts for collection transcription controls.

These checks deliberately keep the browser surface dependency-free while
protecting the request shapes and interaction affordances used by the API.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "src/web/static/collections.html").read_text(encoding="utf-8")
JAVASCRIPT = (ROOT / "src/web/static/js/collections.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/web/static/css/collections.css").read_text(encoding="utf-8")


def test_video_collections_expose_strategy_and_concurrency_controls():
    assert 'name="collection-transcription-strategy"' in HTML
    assert 'value="local"' in HTML
    assert 'value="cloud"' in HTML
    assert 'id="collection-transcription-concurrency"' in HTML
    assert 'min="1" max="3"' in HTML
    assert "local: { min: 1, max: 3, defaultValue: 1 }" in JAVASCRIPT
    assert "cloud: { min: 1, max: 10" in JAVASCRIPT
    assert "document_topic" in JAVASCRIPT


def test_cloud_feedback_is_a_compact_current_collection_status_bar():
    assert HTML.index('class="lc-workspace-head"') < HTML.index(
        'id="collection-transcription-feedback"'
    )
    assert HTML.index('id="collection-transcription-feedback"') < HTML.index(
        'class="lc-meta-bar"'
    )
    assert "lc-quote-summary" in HTML
    assert "确认报价" in JAVASCRIPT
    assert "唯一一次付费确认在明细中完成" not in JAVASCRIPT
    assert 'data-retry-cloud-quote' in JAVASCRIPT


def test_upload_and_continue_send_selected_transcription_policy():
    assert "transcription_strategy: selectedTranscriptionStrategy()" in JAVASCRIPT
    assert "transcription_concurrency: selectedTranscriptionConcurrency()" in JAVASCRIPT
    assert "/continue" in JAVASCRIPT


def test_cloud_quote_confirmation_uses_full_snapshot_and_refresh_endpoint():
    assert "/api/collections/${collectionId}/cloud-quote" in JAVASCRIPT
    assert "/api/collections/${collectionId}/cloud-quote/refresh" in JAVASCRIPT
    assert "/cloud-confirm" in JAVASCRIPT
    assert "transcription_revision: quote.transcription_revision" in JAVASCRIPT
    assert "accepted_total_cny: quote.max_cost_cny" in JAVASCRIPT
    assert "accepted_max_cost_cny: item.max_cost_cny" in JAVASCRIPT
    for state in ("preparing", "failed", "refresh_required", "ready"):
        assert f"quote.state === '{state}'" in JAVASCRIPT


def test_cloud_quote_has_one_explicit_paid_confirmation_and_folder_warning():
    assert "data-confirm-cloud-quote" in JAVASCRIPT
    assert "openCloudQuoteConfirmation" in JAVASCRIPT
    assert "查看并确认" not in JAVASCRIPT
    assert "确认整批云端报价" in JAVASCRIPT
    assert 'id="collection-action-dialog"' in HTML
    assert "提交后不可重复提交" in HTML


def test_new_cloud_quote_opens_the_existing_confirmation_once_after_user_action():
    assert "let cloudQuoteAutoOpenRequested = false;" in JAVASCRIPT
    assert "function requestCloudQuoteConfirmation()" in JAVASCRIPT
    assert "function openRequestedCloudQuoteConfirmation()" in JAVASCRIPT
    assert "if (!cloudQuoteAutoOpenRequested || !cloudQuote" in JAVASCRIPT
    assert "cloudQuoteAutoOpenRequested = false;" in JAVASCRIPT
    assert "openCloudQuoteConfirmation();" in JAVASCRIPT


def test_quote_dialog_cancel_stops_unconfirmed_collection_tasks():
    assert "async function cancelPendingCloudQuote()" in JAVASCRIPT
    assert "cancelLabel: '取消本批任务'" in JAVASCRIPT
    assert "onCancel: cancelPendingCloudQuote" in JAVASCRIPT
    assert "async function cancelActionDialog()" in JAVASCRIPT


def test_stop_and_continue_use_accessible_custom_dialogs_instead_of_confirm():
    stop_and_continue = JAVASCRIPT[
        JAVASCRIPT.index("async function cancelCurrentCollection()") : JAVASCRIPT.index(
            "async function loadCloudQuote("
        )
    ]
    assert 'id="collection-action-dialog"' in HTML
    assert "window.confirm" not in stop_and_continue
    assert "event.key === 'Escape'" in JAVASCRIPT
    assert "els.actionDialog.close()" in stop_and_continue
    assert "提交后不可重复提交" in HTML
    assert "已提交云服务的在途任务会继续" in stop_and_continue
    assert "/api/collections/${collectionId}/cancel" in stop_and_continue
    assert "/api/collections/${currentCollection.id}/continue" in stop_and_continue
    assert ".lc-action-dialog" in CSS


def test_reparse_and_progress_copy_match_real_collection_behavior():
    assert "function isResumableSource(source)" in JAVASCRIPT
    assert "sources.filter(isResumableSource)" in JAVASCRIPT
    assert "if (!['failed', 'canceled'].includes(source.task_status))" not in JAVASCRIPT
    assert "重新解析这条内容" in JAVASCRIPT
    assert "已复用历史解析结果" in JAVASCRIPT
    assert "从提交到完成" in JAVASCRIPT
    assert "逐字稿已完成，AI 解读生成中" in JAVASCRIPT
    assert "function sourceDetailNeedsRefresh(source, detail)" in JAVASCRIPT
    assert "detail.task_status !== source.task_status" in JAVASCRIPT


def test_no_transcript_is_a_terminal_neutral_source_state():
    assert "'no_transcript'" in JAVASCRIPT
    assert "未检测到可转录语音" in JAVASCRIPT


def test_initial_history_restore_does_not_surface_stale_cloud_quote_alert():
    assert "let cloudQuoteFeedbackVisible = false;" in JAVASCRIPT
    assert (
        "cloudQuoteFeedbackVisible = opts.showCloudQuote === true || !opts.silent;"
        in JAVASCRIPT
    )
    assert "cloudQuoteFeedbackVisible\n            && currentCollection" in JAVASCRIPT
    assert "showCloudQuote: true" in JAVASCRIPT
