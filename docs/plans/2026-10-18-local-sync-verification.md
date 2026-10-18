# 2026-10-18 local code synchronization

## Scope

Synchronize current application code, configuration examples, regression tests, production artwork, and design references to `zhangxun-ai/LearnFlux`. Runtime data, credentials, logs, browser evidence, local planning notes, and whiteboard test artifacts remain local. This synchronization does not deploy or publish a release.

## Verification

- `uv run --extra dev pytest --disable-warnings --tb=short -o addopts='' -q`: 2698 passed, 1 skipped, 12 failed. No tests were disabled or removed.
- The two Node behavior checks for history and single-study imports passed during the preceding implementation validation.
- Independent read-only review covered browser sessions, same-origin/CSRF handling, ASR retry claims and ownership, summary completion checks, and Obsidian path/write safety. No supported new blocking finding was reported within those reviewed areas. Real cloud-model calls and real Vault writes were not performed.
- Credential checks compare candidate files against configured secret values without printing those values, and scan for private-key and common token formats. The only initial matches were the public environment-variable name `DASHSCOPE_API_KEY`, not its value.
- Whitespace validation preserves existing CRLF source files by recognizing CR-at-EOL.

## Known failing checks

- `test_app_shell_noise.py::test_production_shells_have_one_content_heading`
- `test_collection_transcription_page.py::test_reparse_and_progress_copy_match_real_collection_behavior`
- `test_study_player_preview_assets.py::test_completed_collection_media_sources_expose_a_contextual_player_entry`
- `test_study_production_assets.py::test_production_navigation_targets_real_study_picker`
- `test_study_production_assets.py::test_completed_collection_media_sources_expose_a_contextual_player_entry`
- `test_trend_radar_backend.py::test_trend_radar_page_route_returns_static_shell`
- `test_unified_product_shell.py::TestNavigationMarkup::test_root_home_is_marketing_landing_without_product_shell`
- `test_unified_product_shell.py::TestNavigationMarkup::test_navigation_generator_reports_no_drift`
- `test_unified_product_shell.py::TestFeatureEntryCoverage::test_home_marketing_cards_link_core_product_surfaces`
- `test_unified_product_shell.py::TestFeatureEntryCoverage::test_root_home_is_self_contained_marketing_page`
- `test_workspace_accessibility.py::test_visual_learning_tabs_have_complete_aria_relationships`
- `test_workspace_accessibility.py::test_visual_learning_skip_link_remains_same_document_without_a_base_url`

These failures were also present in the earlier validation of this local change set. This synchronization does not claim a fully passing suite.

## Pre-existing review finding

The task deletion handler lacks the owner check used by the task mutation handlers. A read-only comparison confirmed the same behavior in the prior `HEAD` (`10ac663`). This is a concrete existing authorization issue for a multi-user setup, not a new regression introduced by the browser-session changes. It was not modified as part of this code-synchronization request.
