#!/usr/bin/env python3
"""Comic Chaos - Web Interface with Interactive Panels"""

import os
import base64
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_from_directory

from src.config import GENERATED_IMAGES_DIR, COMIC_STRIPS_DIR, SETTINGS_DIR
from src.state.static_config import StaticConfig
from src.state.comic_state import ComicState
from settings.setting_registry import SettingRegistry
from src.narratron.narratron import Narratron
from src.image_gen.image_generator import ImageGenerator, MockImageGenerator
from src.comic_strip import ComicStrip
from src.logging.interaction_logger import InteractionLogger


load_dotenv()

app = Flask(__name__)

# Store active sessions
sessions = {}


class ComicSession:
    """A single comic creation session with interactive panels."""

    def __init__(self, comic_id: str, use_real_images: bool = True):
        self.api_key = os.getenv("OPENAI_API_KEY")
        registry = SettingRegistry(settings_dir=SETTINGS_DIR)
        config_dir = registry.get_setting_config_dir(comic_id)

        if not config_dir:
            raise ValueError(f"Comic '{comic_id}' not found")

        self.config = StaticConfig.load_from_directory(str(config_dir))

        if not self.config.blueprint:
            raise ValueError("No blueprint found")

        self.state = None
        self.logger = InteractionLogger(comic_title=self.config.blueprint.title)

        self.narratron = None
        if self.api_key:
            self.narratron = Narratron(
                config=self.config,
                api_key=self.api_key,
                logger=self.logger
            )

        if use_real_images and self.api_key:
            self.image_gen = ImageGenerator(api_key=self.api_key, logger=self.logger)
        else:
            self.image_gen = MockImageGenerator()

        self.comic_strip = None
        self.panels_data = []

    def start(self):
        """Start the comic session and generate opening panel."""
        self.state = ComicState.initialize_from_config(self.config)
        self.comic_strip = ComicStrip(title=self.config.blueprint.title)

        if not self.narratron:
            return {
                "error": "API key not configured",
                "image": None
            }

        response = self.narratron.generate_opening_panel(self.state)

        # Generate image with elements for bubble detection
        image_result = self._generate_image(elements=response.elements)
        image_path = image_result["image_path"]
        detected_bubbles = image_result["detected_bubbles"]

        # Store panel data
        self.panels_data.append({
            "panel_number": 1,
            "image_path": image_path,
            "elements": response.elements,
            "user_input_text": None,
            "detected_bubbles": detected_bubbles,
        })

        return {
            "panel_number": 1,
            "image": self._image_to_base64(image_path),
            "elements": response.elements,
            "detected_bubbles": detected_bubbles,
            "title": self.config.blueprint.title,
            "synopsis": self.config.blueprint.synopsis
        }

    def submit_panel(self, user_input_text: str):
        """Submit user's input for the current panel and generate next panel.

        Args:
            user_input_text: The text the user entered in the input element
        """
        if not self.state or not self.narratron:
            return {"error": "Session not started or API key missing"}

        # Update current panel with user's input
        if self.panels_data:
            self.panels_data[-1]["user_input_text"] = user_input_text

        # Build narrative from current panel's elements + user input
        current_panel = self.panels_data[-1]
        narrative_text = self._build_narrative(current_panel["elements"], user_input_text)

        # Add to comic strip
        panel_num = len(self.panels_data)
        self.state.add_panel(narrative_text, current_panel["image_path"])
        if self.comic_strip:
            self.comic_strip.add_panel(
                current_panel["image_path"],
                narrative_text,
                panel_num,
                elements=current_panel.get("elements"),
                user_input_text=user_input_text,
                detected_bubbles=current_panel.get("detected_bubbles"),
            )

        # Generate next panel based on user's input
        response = self.narratron.process_input(user_input_text, self.state)

        new_location = None
        new_character = None

        if response.new_location:
            new_location = response.new_location.get("name")
        if response.new_character:
            new_character = response.new_character.get("name")

        # Generate image with elements for bubble detection
        image_result = self._generate_image(elements=response.elements)
        image_path = image_result["image_path"]
        detected_bubbles = image_result["detected_bubbles"]
        next_panel_num = panel_num + 1

        # Store next panel data
        self.panels_data.append({
            "panel_number": next_panel_num,
            "image_path": image_path,
            "elements": response.elements,
            "user_input_text": None,
            "detected_bubbles": detected_bubbles,
        })

        return {
            "panel_number": next_panel_num,
            "image": self._image_to_base64(image_path),
            "elements": response.elements,
            "detected_bubbles": detected_bubbles,
            "new_location": new_location,
            "new_character": new_character
        }

    def _build_narrative(self, elements: list, user_input_text: str) -> str:
        """Build narrative text from all elements including user's input."""
        parts = []

        for el in elements:
            el_type = el.get("type", "")
            # Use user's input for the user_input element, otherwise use pre-filled text
            if el.get("user_input"):
                text = user_input_text
            else:
                text = el.get("text", "")

            if not text:
                continue

            if el_type == "speech":
                char_name = el.get("character_name", "Someone")
                parts.append(f'{char_name}: "{text}"')
            elif el_type == "thought":
                char_name = el.get("character_name", "Someone")
                parts.append(f'{char_name} thinks: "{text}"')
            elif el_type == "narration":
                parts.append(f"[{text}]")
            elif el_type == "sfx":
                parts.append(f"*{text}*")

        return " ".join(parts) if parts else "The scene continues..."

    def finish(self):
        """Finish the session and generate the final comic strip."""
        if not self.comic_strip or self.comic_strip.get_panel_count() == 0:
            return {"error": "No panels to export"}

        strip_path = self.comic_strip.generate_comic_strip()
        if not strip_path:
            return {"error": "Failed to generate comic strip"}

        return {
            "strip_image": self._image_to_base64(strip_path),
            "panel_count": self.comic_strip.get_panel_count()
        }

    def _generate_image(self, elements: list | None = None):
        """Generate an image for the current state.

        Args:
            elements: Optional list of elements for bubble generation.

        Returns:
            Dictionary with image_path and detected_bubbles.
        """
        if not self.state:
            return {"image_path": None, "detected_bubbles": []}
        try:
            return self.image_gen.generate_image(
                self.state.render,
                visual_style=self.config.blueprint.visual_style,
                elements=elements,
            )
        except Exception:
            return {"image_path": None, "detected_bubbles": []}

    def _image_to_base64(self, image_path):
        """Convert an image file to base64 string."""
        if not image_path or not Path(image_path).exists():
            return None
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/title_page.png")
def title_page():
    """Serve the title page image."""
    return send_from_directory(".", "title_page.png")


@app.route("/api/comics")
def list_comics():
    """List available comics."""
    registry = SettingRegistry(settings_dir=SETTINGS_DIR)
    settings = registry.get_available_settings()
    return jsonify([
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "style": s.style
        }
        for s in settings
    ])


@app.route("/api/start", methods=["POST"])
def start_comic():
    """Start a new comic session."""
    data = request.get_json()
    comic_id = data.get("comic_id")
    session_id = data.get("session_id")

    if not comic_id or not session_id:
        return jsonify({"error": "Missing comic_id or session_id"}), 400

    try:
        session = ComicSession(comic_id)
        sessions[session_id] = session
        result = session.start()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/submit", methods=["POST"])
def submit_panel():
    """Submit user's input and get the next panel."""
    data = request.get_json()
    session_id = data.get("session_id")
    user_input_text = data.get("user_input", "")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    try:
        result = session.submit_panel(user_input_text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/finish", methods=["POST"])
def finish_comic():
    """Finish and generate the comic strip."""
    data = request.get_json()
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    try:
        result = session.finish()
        del sessions[session_id]
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/assets/<path:filename>")
def serve_asset(filename):
    """Serve generated assets."""
    return send_from_directory("assets", filename)


if __name__ == "__main__":
    Path(GENERATED_IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    Path(COMIC_STRIPS_DIR).mkdir(parents=True, exist_ok=True)
    app.run(debug=True, port=5000)
