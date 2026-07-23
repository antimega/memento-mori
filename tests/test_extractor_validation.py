"""
Archive validation: what counts as a usable Instagram export.

Identity (profile) is required, and there must be at least one kind of content
-- but posts and stories are each optional on their own. A period with only
stories (or only posts) is a normal export, and rejecting it was a bug: the
merge path already tolerates a missing posts file (load_posts_data returns []),
so the only thing standing in the way was this up-front check.

validate_structure() matches by file *presence* via InstagramFileMapper's glob
patterns, not by content, so JSON stubs at the right paths are enough.
"""

import json

import pytest

from memento_mori.extractor import InstagramArchiveExtractor


def _write(path, data=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data if data is not None else []), encoding="utf-8")


def _profile(root):
    # Matches the "**/personal_information/personal_information.json" pattern.
    _write(root / "personal_information" / "personal_information.json", {})


def _posts(root):
    _write(root / "media" / "posts_1.json")          # **/media/posts*.json


def _stories(root):
    _write(root / "media" / "stories.json")          # **/media/stories*.json


def _validate(root):
    ex = InstagramArchiveExtractor()
    ex.extraction_dir = str(root)
    return ex.validate_structure()


def test_stories_only_export_is_valid(tmp_path):
    """The fix: profile + stories, no posts file, is a usable archive."""
    _profile(tmp_path)
    _stories(tmp_path)
    assert _validate(tmp_path) is True


def test_posts_only_export_is_valid(tmp_path):
    """The mirror case: profile + posts, no stories, is also valid."""
    _profile(tmp_path)
    _posts(tmp_path)
    assert _validate(tmp_path) is True


def test_export_with_both_is_valid(tmp_path):
    _profile(tmp_path)
    _posts(tmp_path)
    _stories(tmp_path)
    assert _validate(tmp_path) is True


def test_export_with_no_content_is_invalid(tmp_path):
    """Profile but neither posts nor stories: nothing to build a site from."""
    _profile(tmp_path)
    assert _validate(tmp_path) is False


def test_export_without_profile_is_invalid(tmp_path):
    """Profile is still required even when content is present (regression)."""
    _posts(tmp_path)
    _stories(tmp_path)
    assert _validate(tmp_path) is False
