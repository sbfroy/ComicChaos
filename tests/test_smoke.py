"""Smoke tests for Comic Chaos.

These tests verify core functionality without requiring an OpenAI API key.
They test config loading, blueprint parsing, state management, panel detection,
and text rendering.
"""

import json
from pathlib import Path

import pytest

from src.state.static_config import StaticConfig, Blueprint, ComicConfig, Character, Location
from src.state.comic_state import ComicState, ComicPanel, RenderState
from src.image_gen.panel_detector import PanelDetector, DetectedRegion
from src.image_gen.text_renderer import TextRenderer, TextElement
from src.image_gen.image_generator import MockImageGenerator
from src.comic_strip import ComicStrip
from src.prompt_loader import load_prompt
from comics.comic_registry import ComicRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_blueprint():
    """Create a minimal blueprint for testing."""
    return Blueprint(
        title="Test Comic",
        synopsis="A test comic for CI.",
        locations=[Location(name="Lab", description="A bright laboratory")],
        characters=[Character(name="Testy", description="A round robot with big eyes")],
        visual_style="simple cartoon style",
        rules=["Keep it funny"],
    )


@pytest.fixture
def sample_config(sample_blueprint):
    """Create a StaticConfig with the sample blueprint."""
    return StaticConfig(blueprint=sample_blueprint, comic_config=ComicConfig())


# ---------------------------------------------------------------------------
# Config & Blueprint
# ---------------------------------------------------------------------------

class TestBlueprint:
    def test_blueprint_fields(self, sample_blueprint):
        assert sample_blueprint.title == "Test Comic"
        assert sample_blueprint.starting_location.name == "Lab"
        assert sample_blueprint.main_character.name == "Testy"

    def test_blueprint_from_json(self):
        data = {
            "title": "JSON Comic",
            "synopsis": "Loaded from JSON",
            "locations": [{"name": "Park", "description": "Green park"}],
            "characters": [{"name": "Hero", "description": "Brave hero"}],
            "visual_style": "retro",
        }
        bp = Blueprint(**data)
        assert bp.title == "JSON Comic"
        assert bp.main_character.name == "Hero"

    def test_comic_config_defaults(self):
        cc = ComicConfig()
        assert cc.llm_model == "gpt-4o-mini"
        assert cc.image_size == "1024x1024"


class TestStaticConfigLoading:
    def test_load_from_comics_directory(self):
        """Load a real comic config from the comics/ directory."""
        comics_dir = Path(__file__).resolve().parent.parent / "comics"
        comic_dirs = [
            d for d in comics_dir.iterdir()
            if d.is_dir() and d.name != "archive" and (d / "blueprint.json").exists()
        ]
        if not comic_dirs:
            pytest.skip("No comic directories found")

        config = StaticConfig.load_from_directory(str(comic_dirs[0]))
        assert config.blueprint is not None
        assert config.blueprint.title
        assert config.blueprint.main_character is not None


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

class TestComicState:
    def test_initialize_from_config(self, sample_config):
        state = ComicState.initialize_from_config(sample_config)
        assert state.main_character_name == "Testy"
        assert state.meta.panel_count == 0
        assert state.render.scene_setting == "A bright laboratory"

    def test_add_panel(self, sample_config):
        state = ComicState.initialize_from_config(sample_config)
        panel = state.add_panel("Testy looks around the lab")
        assert panel.panel_number == 1
        assert state.meta.panel_count == 1
        assert len(state.narrative.panels) == 1

    def test_recent_panels(self, sample_config):
        state = ComicState.initialize_from_config(sample_config)
        for i in range(7):
            state.add_panel(f"Panel {i}")
        recent = state.get_recent_panels(3)
        assert len(recent) == 3
        assert recent[0].panel_number == 5

    def test_render_state_model_copy(self):
        rs = RenderState(
            scene_setting="Forest",
            characters_present=["Alice"],
            current_action="Walking",
        )
        copy = rs.model_copy()
        copy.scene_setting = "Cave"
        assert rs.scene_setting == "Forest"


# ---------------------------------------------------------------------------
# Comic Registry
# ---------------------------------------------------------------------------

class TestComicRegistry:
    def test_discover_comics(self):
        comics_dir = Path(__file__).resolve().parent.parent / "comics"
        registry = ComicRegistry(comics_dir=comics_dir)
        comics = registry.get_available_comics()
        # Should find at least one comic (paul_the_panda or superhero_simen)
        assert len(comics) >= 1
        assert all(c.id for c in comics)
        assert all(c.name for c in comics)

    def test_get_comic_config_dir(self):
        comics_dir = Path(__file__).resolve().parent.parent / "comics"
        registry = ComicRegistry(comics_dir=comics_dir)
        comics = registry.get_available_comics()
        if comics:
            config_dir = registry.get_comic_config_dir(comics[0].id)
            assert config_dir is not None
            assert config_dir.exists()

    def test_nonexistent_comic(self):
        comics_dir = Path(__file__).resolve().parent.parent / "comics"
        registry = ComicRegistry(comics_dir=comics_dir)
        assert registry.get_comic_config_dir("nonexistent_comic_xyz") is None


# ---------------------------------------------------------------------------
# Panel Detection (unit-level)
# ---------------------------------------------------------------------------

class TestPanelDetector:
    def test_init_defaults(self):
        detector = PanelDetector()
        assert detector.min_area == 70000
        assert detector.min_circularity == 0.52

    def test_empty_image_returns_no_bubbles(self):
        """An all-black image should produce no detected bubbles."""
        import numpy as np
        from PIL import Image
        from io import BytesIO

        img = Image.new("RGB", (1024, 1024), (0, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        detector = PanelDetector()
        bubbles = detector.detect_bubbles(image_bytes)
        assert bubbles == []


# ---------------------------------------------------------------------------
# Text Renderer
# ---------------------------------------------------------------------------

class TestTextRenderer:
    def test_wrap_text(self):
        renderer = TextRenderer()
        font = renderer._get_font(24)
        lines = renderer._wrap_text("Hello world this is a test", font, 100)
        assert len(lines) >= 1

    def test_font_size_lookup(self):
        renderer = TextRenderer()
        assert renderer._get_target_font_size("Hi", "speech") == 46
        assert renderer._get_target_font_size("A" * 60, "speech") == 32
        assert renderer._get_target_font_size("Hi", "narration") == 52


# ---------------------------------------------------------------------------
# Mock Image Generator
# ---------------------------------------------------------------------------

class TestMockImageGenerator:
    def test_generate_returns_none_bytes(self):
        gen = MockImageGenerator()
        rs = RenderState(scene_setting="Lab", characters_present=[], current_action="Testing")
        result = gen.generate_image(rs)
        assert result["image_bytes"] is None
        assert result["detected_bubbles"] == []


# ---------------------------------------------------------------------------
# Prompt Loader
# ---------------------------------------------------------------------------

class TestPromptLoader:
    def test_load_and_substitute(self, tmp_path):
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Hello {name}, welcome to {place}!")
        result = load_prompt(prompt_file, name="Alice", place="Wonderland")
        assert result == "Hello Alice, welcome to Wonderland!"

    def test_load_without_substitution(self, tmp_path):
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("No variables here.")
        result = load_prompt(prompt_file)
        assert result == "No variables here."


# ---------------------------------------------------------------------------
# Comic Strip
# ---------------------------------------------------------------------------

class TestComicStrip:
    def test_empty_strip(self):
        strip = ComicStrip(title="Test")
        assert strip.get_panel_count() == 0
        assert strip.generate_comic_strip() is None

    def test_add_panel(self):
        strip = ComicStrip(title="Test")
        strip.add_panel(None, "Narrative", 1)
        assert strip.get_panel_count() == 1
        # With no valid image bytes, generation should return None
        assert strip.generate_comic_strip() is None
