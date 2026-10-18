"""A successful upload must keep a recent-task entry and navigate to its view."""

from tests.unit.test_single_study_behavior import test_single_study_import_behavior as _check_import_behavior


def test_local_media_upload_is_added_to_recent_history():
    # The Node flow asserts a 202 upload adds the media task, title and view link.
    _check_import_behavior()
