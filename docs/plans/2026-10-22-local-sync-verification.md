# 2026-10-22 local code synchronization

## Scope

Synchronize the complete current application change set to `zhangxun-ai/LearnFlux` on `main`: shared Xiaohongshu URL/API acquisition, optional independent Feishu archiving, local browser management identity, canonical leaf icons, and Beijing time display/calendar filters. Include configuration examples, documentation, and regression tests. This operation does not deploy the application or create a release.

Live credentials, user configuration, tunnel/LaunchAgent configuration, runtime databases, source media, logs, and browser artifacts are excluded.

## Verification

- `uv run --extra dev pytest -o addopts='' -q --disable-warnings --tb=short`: **2743 passed, 1 skipped, 31 failed**. The default offline suite ran without disabling or removing tests. Failure names are listed below; this synchronization does not claim a fully passing suite.
- The preceding Beijing-time implementation validation passed 156 focused tests plus 2 service-worker cache checks. The current complete run also passes those checks.
- Xiaohongshu URL/API/downloader, Feishu archive, browser-session security, and timezone regressions pass in the complete run. These checks use mocks; they do not establish current remote-provider availability or perform real Feishu writes.
- Browser verification against the local service confirmed explicit `+08:00` task timestamps, consistent recent-task rendering under UTC and America/Los_Angeles host timezones, and successful loading of six related pages with `Asia/Shanghai` rules and no observed page errors.
- Candidate files were checked against configured credential values without printing those values, and scanned for private keys and common credential formats: no findings. `git diff --check` passed.
- GitNexus change detection was run after the implementation edits. Its whole-worktree report includes pre-existing local changes in authentication and platform acquisition as well as the time fix.

## Failing checks

- `tests/unit/test_app_shell_noise.py::test_production_shells_have_one_content_heading`
- `tests/unit/test_collection_transcription_page.py::test_reparse_and_progress_copy_match_real_collection_behavior`
- `tests/unit/test_learning_collections.py::test_collection_source_retry_requeues_failed_local_source`
- `tests/unit/test_learning_collections.py::test_collection_source_reveal_opens_preserved_local_file`
- `tests/unit/test_learning_collections.py::test_collection_api_generates_and_reads_knowledge_map`
- `tests/unit/test_learning_collections.py::test_collection_upload_reuses_cached_local_file`
- `tests/unit/test_learning_collections.py::test_collection_upload_appends_after_existing_sources`
- `tests/unit/test_learning_collections.py::test_collection_upload_inserts_numbered_source_by_filename_prefix`
- `tests/unit/test_learning_collections.py::test_cancel_collection_processing_only_cancels_unfinished_sources`
- `tests/unit/test_learning_collections.py::test_collection_api_filters_and_options`
- `tests/unit/test_study_player_preview_assets.py::test_completed_collection_media_sources_expose_a_contextual_player_entry`
- `tests/unit/test_study_production_assets.py::test_production_navigation_targets_real_study_picker`
- `tests/unit/test_study_production_assets.py::test_completed_collection_media_sources_expose_a_contextual_player_entry`
- `tests/unit/test_study_routes.py::test_get_study_session_returns_read_model`
- `tests/unit/test_study_routes.py::test_create_study_note`
- `tests/unit/test_study_routes.py::test_single_note_document_get_and_put_use_owned_context`
- `tests/unit/test_study_routes.py::test_single_obsidian_sync_maps_per_file_result_status[result0-200]`
- `tests/unit/test_study_routes.py::test_single_obsidian_sync_maps_per_file_result_status[result1-207]`
- `tests/unit/test_study_routes.py::test_single_obsidian_sync_maps_per_file_result_status[result2-500]`
- `tests/unit/test_study_routes.py::test_obsidian_conflict_payload_returns_409`
- `tests/unit/test_study_routes.py::test_conflict_resolution_forwards_all_stale_preconditions`
- `tests/unit/test_study_routes.py::test_ask_study_ai`
- `tests/unit/test_study_routes.py::test_export_study_markdown`
- `tests/unit/test_trend_radar_backend.py::test_trend_radar_page_route_returns_static_shell`
- `tests/unit/test_ui_lab.py::test_review_ui_lab_assets_are_isolated_and_mock_only`
- `tests/unit/test_unified_product_shell.py::TestNavigationMarkup::test_root_home_is_marketing_landing_without_product_shell`
- `tests/unit/test_unified_product_shell.py::TestNavigationMarkup::test_navigation_generator_reports_no_drift`
- `tests/unit/test_unified_product_shell.py::TestFeatureEntryCoverage::test_home_marketing_cards_link_core_product_surfaces`
- `tests/unit/test_unified_product_shell.py::TestFeatureEntryCoverage::test_root_home_is_self_contained_marketing_page`
- `tests/unit/test_workspace_accessibility.py::test_visual_learning_tabs_have_complete_aria_relationships`
- `tests/unit/test_workspace_accessibility.py::test_visual_learning_skip_link_remains_same_document_without_a_base_url`
