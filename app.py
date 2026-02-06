#!/usr/bin/env python3
"""Comic Chaos - Web Interface with Interactive Panels"""

import os
import json
import base64

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response

from src.config import SETTINGS_DIR
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
            self.image_gen = ImageGenerator(comic_config=self.config.comic_config, api_key=self.api_key, logger=self.logger)
        else:
            self.image_gen = MockImageGenerator()

        self.comic_strip = None
        self.panels_data = []

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

        strip_bytes = self.comic_strip.generate_comic_strip()
        if not strip_bytes:
            return {"error": "Failed to generate comic strip"}

        return {
            "strip_image": base64.b64encode(strip_bytes).decode("utf-8"),
            "panel_count": self.comic_strip.get_panel_count()
        }

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
                main_character_description=f"{self.state.main_character_name}: {self.state.main_character_description}",
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
        title_card_bytes = None

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
                title_card_bytes = event["image_bytes"]
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
            "image_bytes": title_card_bytes,
            "elements": [],
            "user_input_text": None,
            "detected_bubbles": [],
            "is_title_card": True,
            "is_auto": False,
        })

        # Add title card to comic strip
        if self.comic_strip and title_card_bytes:
            self.comic_strip.add_panel(
                title_card_bytes,
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
        first_panel_bytes = None
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
                first_panel_bytes = event["image_bytes"]
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
            "image_bytes": first_panel_bytes,
            "elements": response.first_panel.elements,
            "user_input_text": None,
            "detected_bubbles": first_panel_bubbles,
            "is_title_card": False,
            "is_auto": False,
        })

    def _rollback_state(self, state_snapshot, comic_strip_count: int, panels_data_count: int):
        """Restore session to a previous snapshot after a failed panel generation."""
        self.state = state_snapshot
        if self.comic_strip:
            self.comic_strip.panels = self.comic_strip.panels[:comic_strip_count]
        self.panels_data = self.panels_data[:panels_data_count]
        if self.panels_data:
            self.panels_data[-1]["user_input_text"] = None

    def submit_panel_streaming(self, user_input_text: str):
        """Submit user's input and stream the next panel(s) generation.

        May yield one or two panels: an optional automatic transition panel
        followed by an interactive panel. If image generation fails (e.g.
        content policy rejection), all state changes are rolled back so the
        user can retry with different input.
        """
        if not self.state or not self.narratron:
            yield json.dumps({"type": "error", "error": "Session not started"})
            return

        # Snapshot state for rollback on error
        state_snapshot = self.state.model_copy(deep=True)
        comic_strip_count = len(self.comic_strip.panels) if self.comic_strip else 0
        panels_data_count = len(self.panels_data)

        # Update current panel with user's input
        if self.panels_data:
            self.panels_data[-1]["user_input_text"] = user_input_text

        # Build narrative from current panel's elements + user input
        current_panel = self.panels_data[-1]
        narrative_text = self._build_narrative(current_panel["elements"], user_input_text)

        # Add to comic strip
        panel_num = len(self.panels_data)
        self.state.add_panel(narrative_text)
        if self.comic_strip:
            self.comic_strip.add_panel(
                current_panel["image_bytes"],
                narrative_text,
                panel_num,
                elements=current_panel.get("elements"),
                user_input_text=user_input_text,
                detected_bubbles=current_panel.get("detected_bubbles"),
            )

        # Generate next panel(s) based on user's input
        response = self.narratron.process_input(user_input_text, self.state)

        # Stream each panel in the response (1 or 2 panels)
        for i, panel_data in enumerate(response.panels):
            is_auto = panel_data.is_auto
            next_panel_num = panel_num + 1 + i

            # For auto panels, temporarily override render state
            saved_render = None
            if is_auto and panel_data.scene_description:
                saved_render = self.state.render.model_copy()
                self.state.render.current_action = panel_data.scene_description

            # Choose SSE event types based on panel type
            init_type = "init_auto" if is_auto else "init"
            complete_type = "complete_auto" if is_auto else "complete"

            # Send init event
            yield json.dumps({
                "type": init_type,
                "panel_number": next_panel_num,
                "elements": panel_data.elements,
                "is_auto": is_auto,
            })

            # Generate image with streaming
            image_bytes = None
            detected_bubbles = []

            for event in self._generate_image_streaming(elements=panel_data.elements):
                if event["type"] == "partial":
                    yield json.dumps({
                        "type": "partial",
                        "panel_number": next_panel_num,
                        "image_base64": event["image_base64"],
                        "partial_index": event["partial_index"],
                    })
                elif event["type"] == "complete":
                    image_bytes = event["image_bytes"]
                    detected_bubbles = event["detected_bubbles"]
                    yield json.dumps({
                        "type": complete_type,
                        "panel_number": next_panel_num,
                        "image_base64": event["image_base64"],
                        "detected_bubbles": detected_bubbles,
                        "elements": panel_data.elements,
                        "is_auto": is_auto,
                    })
                elif event["type"] == "error":
                    self._rollback_state(state_snapshot, comic_strip_count, panels_data_count)
                    yield json.dumps({"type": "error", "error": event["error"]})
                    return

            # Restore render state after auto panel
            if saved_render:
                self.state.render = saved_render

            # For auto panels, add to state and comic strip immediately
            if is_auto:
                auto_narrative = self._build_narrative(panel_data.elements, "")
                self.state.add_panel(auto_narrative)
                if self.comic_strip:
                    self.comic_strip.add_panel(
                        image_bytes, auto_narrative, next_panel_num,
                        elements=panel_data.elements,
                        user_input_text=None,
                        detected_bubbles=detected_bubbles,
                    )

            # Store panel data
            self.panels_data.append({
                "panel_number": next_panel_num,
                "image_bytes": image_bytes,
                "elements": panel_data.elements,
                "user_input_text": None,
                "detected_bubbles": detected_bubbles,
                "is_auto": is_auto,
            })

        # Check if the story has reached a final outcome
        if self.state.reached_outcome:
            finale_panel_num = next_panel_num + 1

            finale_card = TitleCardPanel(
                scene_description=(
                    f"A dramatic, cinematic closing shot for {self.config.blueprint.title}. "
                    f"The words 'The End' are displayed prominently in the scene. "
                    f"{self.state.reached_outcome}"
                ),
                title_treatment="The End",
                atmosphere="finale",
            )

            yield json.dumps({
                "type": "init_finale",
                "panel_number": finale_panel_num,
                "title": "The End",
                "reached_outcome": self.state.reached_outcome,
                "is_finale": True,
            })

            finale_bytes = None
            for event in self._generate_title_card_streaming(
                finale_card,
                self.config.blueprint.visual_style
            ):
                if event["type"] == "partial":
                    yield json.dumps({
                        "type": "partial",
                        "panel_number": finale_panel_num,
                        "image_base64": event["image_base64"],
                        "partial_index": event["partial_index"],
                    })
                elif event["type"] == "complete":
                    finale_bytes = event["image_bytes"]
                    yield json.dumps({
                        "type": "complete_finale",
                        "panel_number": finale_panel_num,
                        "image_base64": event["image_base64"],
                        "is_finale": True,
                        "reached_outcome": self.state.reached_outcome,
                    })
                elif event["type"] == "error":
                    yield json.dumps({"type": "error", "error": event["error"]})

            # Store finale panel data
            self.panels_data.append({
                "panel_number": finale_panel_num,
                "image_bytes": finale_bytes,
                "elements": [],
                "user_input_text": None,
                "detected_bubbles": [],
                "is_finale": True,
                "is_auto": False,
            })

            # Add finale to comic strip
            if self.comic_strip and finale_bytes:
                self.comic_strip.add_panel(
                    finale_bytes,
                    f"The End - {self.state.reached_outcome}",
                    finale_panel_num,
                    elements=[],
                    user_input_text=None,
                    detected_bubbles=[],
                )


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
            "style": s.style,
            "panel_font": s.panel_font,
        }
        for s in settings
    ])


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
    app.run(debug=True, port=5000)
