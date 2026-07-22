"""
Theme overlay: `--theme <dir>` lets a site shadow templates and overlay static
assets without editing the generator. These tests pin the three guarantees the
feature makes — template shadowing, static overlay, and that no theme leaves
behaviour untouched — at the unit level, without paying for the media pipeline.
"""

from jinja2 import ChoiceLoader, FileSystemLoader

from memento_mori.generator import InstagramSiteGenerator


def _generator(out_dir, theme_dir=None):
    """A generator over an empty package — enough to exercise loaders/overlay."""
    return InstagramSiteGenerator({"sources": {}}, out_dir, theme_dir=theme_dir)


class TestTemplateShadowing:
    def test_theme_template_wins_over_default(self, tmp_path):
        theme = tmp_path / "theme"
        (theme / "templates").mkdir(parents=True)
        # _footer.html is a real default partial; shadow it.
        (theme / "templates" / "_footer.html").write_text(
            "THEME_FOOTER_MARKER", encoding="utf-8"
        )
        gen = _generator(tmp_path / "out", theme_dir=theme)
        rendered = gen.jinja_env.get_template("_footer.html").render()
        assert "THEME_FOOTER_MARKER" in rendered

    def test_non_overridden_template_falls_through_to_default(self, tmp_path):
        theme = tmp_path / "theme"
        (theme / "templates").mkdir(parents=True)
        (theme / "templates" / "_footer.html").write_text("x", encoding="utf-8")
        gen = _generator(tmp_path / "out", theme_dir=theme)
        # index.html is not in the theme, so the default must still resolve.
        assert gen.jinja_env.get_template("index.html") is not None

    def test_missing_theme_templates_dir_is_tolerated(self, tmp_path):
        theme = tmp_path / "theme"  # exists but has no templates/ subdir
        theme.mkdir()
        gen = _generator(tmp_path / "out", theme_dir=theme)
        assert gen.jinja_env.get_template("index.html") is not None


class TestStaticOverlay:
    def test_theme_static_file_overwrites_default(self, tmp_path):
        out = tmp_path / "out"
        (out / "css").mkdir(parents=True)
        (out / "css" / "style.css").write_text("DEFAULT", encoding="utf-8")

        theme = tmp_path / "theme"
        (theme / "static" / "css").mkdir(parents=True)
        (theme / "static" / "css" / "style.css").write_text("THEMED", encoding="utf-8")

        gen = _generator(out, theme_dir=theme)
        gen._overlay_theme_static()

        assert (out / "css" / "style.css").read_text(encoding="utf-8") == "THEMED"

    def test_theme_can_add_a_brand_new_asset(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()

        theme = tmp_path / "theme"
        (theme / "static" / "css").mkdir(parents=True)
        (theme / "static" / "css" / "extra.css").write_text("NEW", encoding="utf-8")

        gen = _generator(out, theme_dir=theme)
        gen._overlay_theme_static()

        assert (out / "css" / "extra.css").read_text(encoding="utf-8") == "NEW"

    def test_missing_theme_static_dir_is_a_noop(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        theme = tmp_path / "theme"
        theme.mkdir()
        gen = _generator(out, theme_dir=theme)
        gen._overlay_theme_static()  # must not raise
        assert list(out.iterdir()) == []


class TestNoTheme:
    def test_loader_is_plain_without_a_theme(self, tmp_path):
        gen = _generator(tmp_path / "out")
        assert gen.theme_dir is None
        assert isinstance(gen.jinja_env.loader, FileSystemLoader)
        assert not isinstance(gen.jinja_env.loader, ChoiceLoader)

    def test_loader_is_a_choiceloader_with_a_theme(self, tmp_path):
        theme = tmp_path / "theme"
        (theme / "templates").mkdir(parents=True)
        gen = _generator(tmp_path / "out", theme_dir=theme)
        assert isinstance(gen.jinja_env.loader, ChoiceLoader)
