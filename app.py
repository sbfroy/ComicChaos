#!/usr/bin/env python3
"""Comic Chaos - Web Interface with Interactive Panels"""

import os
import json
import base64
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response

from src.config import GENERATED_IMAGES_DIR, COMIC_STRIPS_DIR, SETTINGS_DIR
from src.state.static_config import StaticConfig
from src.state.comic_state import ComicState
from settings.setting_registry import SettingRegistry
from src.narratron.narratron import Narratron, TitleCardPanel
from src.state.comic_state import RenderState
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
        """Start the comic session with grand opening sequence.

        Generates both a title card panel and the first interactive panel.
        """
        self.state = ComicState.initialize_from_config(self.config)
        self.comic_strip = ComicStrip(title=self.config.blueprint.title)

        if not self.narratron:
            return {
                "error": "API key not configured",
                "image": None
            }

        # Generate opening sequence (title card + first panel)
        response = self.narratron.generate_opening_sequence(self.state)

        # Generate title card image (no bubble detection)
        title_card_image = self._generate_title_card_image(
            response.title_card,
            self.config.blueprint.visual_style
        )

        # Store title card panel data (panel 0)
        self.panels_data.append({
            "panel_number": 0,
            "image_path": title_card_image["image_path"],
            "elements": [],
            "user_input_text": None,
            "detected_bubbles": [],
            "is_title_card": True,
        })

        # Generate first interactive panel (with bubble detection)
        first_panel_image = self._generate_image(elements=response.first_panel.elements)

        # Store first panel data (panel 1)
        self.panels_data.append({
            "panel_number": 1,
            "image_path": first_panel_image["image_path"],
            "elements": response.first_panel.elements,
            "user_input_text": None,
            "detected_bubbles": first_panel_image["detected_bubbles"],
            "is_title_card": False,
        })

        return {
            "panels": [
                {
                    "panel_number": 0,
                    "image": self._image_to_base64(title_card_image["image_path"]),
                    "elements": [],
                    "detected_bubbles": [],
                    "is_title_card": True,
                    "title": self.config.blueprint.title,
                    "atmosphere": response.title_card.atmosphere,
                },
                {
                    "panel_number": 1,
                    "image": self._image_to_base64(first_panel_image["image_path"]),
                    "elements": response.first_panel.elements,
                    "detected_bubbles": first_panel_image["detected_bubbles"],
                    "is_title_card": False,
                },
            ],
            "title": self.config.blueprint.title,
            "synopsis": self.config.blueprint.synopsis
        }

    def _generate_title_card_image(self, title_card: TitleCardPanel, visual_style: str):
        """Generate title card image without bubble detection.

        Args:
            title_card: The title card panel data.
            visual_style: The visual style for the comic.

        Returns:
            Dictionary with image_path and empty detected_bubbles.
        """
        render_state = RenderState(
            scene_setting=title_card.scene_description,
            characters_present=[],
            current_action=title_card.atmosphere,
        )

        return self.image_gen.generate_image(
            render_state,
            visual_style=visual_style,
            elements=None,  # No bubbles for title card
        )

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

    def _generate_image_streaming(self, elements: list | None = None):
        """Generate an image with streaming for the current state.

        Yields partial and complete image events.
        """
        if not self.state:
            yield {"type": "error", "error": "No state"}
            return

        try:
            for event in self.image_gen.generate_image_streaming(
                self.state.render,
                visual_style=self.config.blueprint.visual_style,
                elements=elements,
            ):
                yield event
        except Exception as e:
            yield {"type": "error", "error": str(e)}

    def _generate_title_card_streaming(self, title_card: TitleCardPanel, visual_style: str):
        """Generate title card image with streaming.

        Yields partial and complete image events for the title card.
        """
        render_state = RenderState(
            scene_setting=title_card.scene_description,
            characters_present=[],
            current_action=title_card.atmosphere,
        )

        try:
            for event in self.image_gen.generate_image_streaming(
                render_state,
                visual_style=visual_style,
                elements=None,  # No bubbles for title card
            ):
                yield event
        except Exception as e:
            yield {"type": "error", "error": str(e)}

    def start_streaming(self):
        """Start the comic session with streaming for grand opening sequence.

        Generates both title card and first interactive panel with streaming.
        """
        self.state = ComicState.initialize_from_config(self.config)
        self.comic_strip = ComicStrip(title=self.config.blueprint.title)

        if not self.narratron:
            yield json.dumps({"type": "error", "error": "API key not configured"})
            return

        # Generate opening sequence (title card + first panel)
        response = self.narratron.generate_opening_sequence(self.state)

        # === TITLE CARD ===
        yield json.dumps({
            "type": "init_title_card",
            "panel_number": 0,
            "title": self.config.blueprint.title,
            "atmosphere": response.title_card.atmosphere,
            "is_title_card": True,
        })

        # Generate title card image with streaming
        title_card_path = None

        for event in self._generate_title_card_streaming(
            response.title_card,
            self.config.blueprint.visual_style
        ):
            if event["type"] == "partial":
                yield json.dumps({
                    "type": "partial",
                    "panel_number": 0,
                    "image_base64": event["image_base64"],
                    "partial_index": event["partial_index"],
                })
            elif event["type"] == "complete":
                title_card_path = event["image_path"]
                yield json.dumps({
                    "type": "complete_title_card",
                    "panel_number": 0,
                    "image_base64": event["image_base64"],
                    "is_title_card": True,
                })
            elif event["type"] == "error":
                yield json.dumps({"type": "error", "error": event["error"]})
                return

        # Store title card panel data
        self.panels_data.append({
            "panel_number": 0,
            "image_path": title_card_path,
            "elements": [],
            "user_input_text": None,
            "detected_bubbles": [],
            "is_title_card": True,
        })

        # Add title card to comic strip
        if self.comic_strip and title_card_path:
            self.comic_strip.add_panel(
                title_card_path,
                f"{self.config.blueprint.title} - {response.title_card.atmosphere}",
                0,
                elements=[],
                user_input_text=None,
                detected_bubbles=[],
            )

        # === FIRST INTERACTIVE PANEL ===
        yield json.dumps({
            "type": "init",
            "panel_number": 1,
            "elements": response.first_panel.elements,
            "title": self.config.blueprint.title,
            "synopsis": self.config.blueprint.synopsis,
            "is_title_card": False,
        })

        # Generate first panel image with streaming
        first_panel_path = None
        first_panel_bubbles = []

        for event in self._generate_image_streaming(elements=response.first_panel.elements):
            if event["type"] == "partial":
                yield json.dumps({
                    "type": "partial",
                    "panel_number": 1,
                    "image_base64": event["image_base64"],
                    "partial_index": event["partial_index"],
                })
            elif event["type"] == "complete":
                first_panel_path = event["image_path"]
                first_panel_bubbles = event["detected_bubbles"]
                yield json.dumps({
                    "type": "complete",
                    "panel_number": 1,
                    "image_base64": event["image_base64"],
                    "detected_bubbles": first_panel_bubbles,
                    "is_title_card": False,
                })
            elif event["type"] == "error":
                yield json.dumps({"type": "error", "error": event["error"]})
                return

        # Store first panel data
        self.panels_data.append({
            "panel_number": 1,
            "image_path": first_panel_path,
            "elements": response.first_panel.elements,
            "user_input_text": None,
            "detected_bubbles": first_panel_bubbles,
            "is_title_card": False,
        })

    def submit_panel_streaming(self, user_input_text: str):
        """Submit user's input and stream the next panel generation."""
        if not self.state or not self.narratron:
            yield json.dumps({"type": "error", "error": "Session not started"})
            return

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

        next_panel_num = panel_num + 1

        # Send initial data for next panel
        yield json.dumps({
            "type": "init",
            "panel_number": next_panel_num,
            "elements": response.elements,
        })

        # Generate image with streaming
        image_path = None
        detected_bubbles = []

        for event in self._generate_image_streaming(elements=response.elements):
            if event["type"] == "partial":
                yield json.dumps({
                    "type": "partial",
                    "image_base64": event["image_base64"],
                    "partial_index": event["partial_index"],
                })
            elif event["type"] == "complete":
                image_path = event["image_path"]
                detected_bubbles = event["detected_bubbles"]
                yield json.dumps({
                    "type": "complete",
                    "image_base64": event["image_base64"],
                    "detected_bubbles": detected_bubbles,
                })
            elif event["type"] == "error":
                yield json.dumps({"type": "error", "error": event["error"]})
                return

        # Store next panel data
        self.panels_data.append({
            "panel_number": next_panel_num,
            "image_path": image_path,
            "elements": response.elements,
            "user_input_text": None,
            "detected_bubbles": detected_bubbles,
        })

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


@app.route("/api/start-stream", methods=["POST"])
def start_comic_stream():
    """Start a new comic session with streaming image generation."""
    data = request.get_json()
    comic_id = data.get("comic_id")
    session_id = data.get("session_id")

    if not comic_id or not session_id:
        return jsonify({"error": "Missing comic_id or session_id"}), 400

    try:
        session = ComicSession(comic_id)
        sessions[session_id] = session

        def generate():
            for event in session.start_streaming():
                yield f"data: {event}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/submit-stream", methods=["POST"])
def submit_panel_stream():
    """Submit user's input and stream the next panel generation."""
    data = request.get_json()
    session_id = data.get("session_id")
    user_input_text = data.get("user_input", "")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    def generate():
        for event in session.submit_panel_streaming(user_input_text):
            yield f"data: {event}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


if __name__ == "__main__":
    Path(GENERATED_IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    Path(COMIC_STRIPS_DIR).mkdir(parents=True, exist_ok=True)
    app.run(debug=True, port=5000)
