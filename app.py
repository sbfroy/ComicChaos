#!/usr/bin/env python3
"""Comic Chaos - Web Interface with Interactive Panels"""

import os
import pickle

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from src.config import COMICS_DIR
from comics.comic_registry import ComicRegistry
from src.comic_session import ComicSession
from src.comic_strip import ComicStrip

SESSIONS_DIR = "/tmp/comic_chaos_sessions"


load_dotenv()

app = Flask(__name__)

# Rate limiting — generous defaults to avoid disrupting active comic sessions.
# The expensive endpoints (start-stream, submit-stream) get tighter per-route limits.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["120 per minute"],
    storage_uri="memory://",
)

# API availability toggle — set API_ENABLED=false in Railway to disable comic generation.
api_enabled = os.getenv("API_ENABLED", "true").lower() == "true"

# Store active sessions (in-memory cache — recovered from disk on miss)
sessions = {}


def save_session(session_id, session):
    """Checkpoint session state to disk for cross-worker and crash recovery."""
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        data = {
            "comic_id": session.comic_id,
            "language": session.language,
            "state": session.state,
            "panels_data": session.panels_data,
        }
        path = os.path.join(SESSIONS_DIR, f"{session_id}.pkl")
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        print(f"[SESSION] Failed to save checkpoint: {e}")


def recover_session(session_id):
    """Try to recover a session from a disk checkpoint."""
    path = os.path.join(SESSIONS_DIR, f"{session_id}.pkl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)

        # Recreate session (this rebuilds narratron, image_gen, etc.)
        session = ComicSession(data["comic_id"], language=data["language"])
        session.state = data["state"]
        session.panels_data = data["panels_data"]

        # Rebuild comic strip from panels_data
        session.comic_strip = ComicStrip(title=session.config.blueprint.title)
        for panel in data["panels_data"]:
            if panel.get("image_bytes"):
                session.comic_strip.add_panel(
                    panel["image_bytes"],
                    panel.get("user_input_text") or "",
                    panel["panel_number"],
                    elements=panel.get("elements"),
                    user_input_text=panel.get("user_input_text"),
                    detected_bubbles=panel.get("detected_bubbles"),
                )

        print(f"[SESSION] Recovered session {session_id}")
        return session
    except Exception as e:
        print(f"[SESSION] Failed to recover: {e}")
        return None


def cleanup_session_file(session_id):
    """Remove session checkpoint from disk."""
    try:
        path = os.path.join(SESSIONS_DIR, f"{session_id}.pkl")
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def get_session(session_id):
    """Look up a session from memory, falling back to disk recovery."""
    session = sessions.get(session_id)
    if session:
        return session

    # Not in this worker's memory — try to recover from disk
    session = recover_session(session_id)
    if session:
        sessions[session_id] = session
    return session


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Check if the API is available for comic generation."""
    return jsonify({"api_available": api_enabled})


@app.route("/api/comics")
def list_comics():
    """List available comics."""
    registry = ComicRegistry(comics_dir=COMICS_DIR)
    comics = registry.get_available_comics()
    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "name_no": c.name_no,
            "description": c.description,
            "description_no": c.description_no,
            "style": c.style,
            "panel_font": c.panel_font,
        }
        for c in comics
    ])


@app.route("/api/finish", methods=["POST"])
def finish_comic():
    """Finish and generate the comic strip."""
    data = request.get_json()
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    session = get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    try:
        result = session.finish()
        sessions.pop(session_id, None)
        cleanup_session_file(session_id)
        return jsonify(result)
    except Exception as e:
        print(f"Error finishing comic: {e}")
        return jsonify({"error": "Failed to generate comic strip"}), 500


@app.route("/api/start-stream", methods=["POST"])
@limiter.limit("6 per minute")
def start_comic_stream():
    """Start a new comic session with streaming image generation."""
    if not api_enabled:
        return jsonify({"error": "API temporarily unavailable"}), 503

    data = request.get_json()
    comic_id = data.get("comic_id")
    session_id = data.get("session_id")
    language = data.get("language", "no")

    if not comic_id or not session_id:
        return jsonify({"error": "Missing comic_id or session_id"}), 400

    try:
        session = ComicSession(comic_id, language=language)
        sessions[session_id] = session

        def generate():
            for event in session.start_streaming():
                yield f"data: {event}\n\n"
            save_session(session_id, session)

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
        print(f"Error starting comic: {e}")
        return jsonify({"error": "Failed to start comic session"}), 500


@app.route("/api/submit-stream", methods=["POST"])
@limiter.limit("10 per minute")
def submit_panel_stream():
    """Submit user's input and stream the next panel generation."""
    if not api_enabled:
        return jsonify({"error": "API temporarily unavailable"}), 503

    data = request.get_json()
    session_id = data.get("session_id")
    user_input_text = data.get("user_input", "")
    language = data.get("language", "no")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    session = get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    # Update language in case user switched mid-session
    session.language = language
    if session.narratron:
        session.narratron.language = language

    def generate():
        for event in session.submit_panel_streaming(user_input_text):
            yield f"data: {event}\n\n"
        save_session(session_id, session)

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
    app.run(debug=os.getenv("DEBUG", "false").lower() == "true", port=5000)
