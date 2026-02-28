#!/usr/bin/env python3
"""Comic Chaos - Web Interface with Interactive Panels"""

import os
import pickle
import time

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

# Track last-access time per session for TTL-based eviction.
session_timestamps = {}
SESSION_TTL_SECONDS = 3600  # 60 minutes


def touch_session(session_id):
    """Record that a session was just accessed."""
    session_timestamps[session_id] = time.monotonic()


def cleanup_stale_sessions():
    """Evict sessions that haven't been accessed within the TTL.

    Removes both in-memory session objects and on-disk pickle checkpoints.
    Called at the start of new session creation to keep memory bounded.
    """
    now = time.monotonic()
    stale = [
        sid for sid, ts in session_timestamps.items()
        if now - ts > SESSION_TTL_SECONDS
    ]
    for sid in stale:
        sessions.pop(sid, None)
        session_timestamps.pop(sid, None)
        cleanup_session_file(sid)
    if stale:
        print(f"[SESSION] Cleaned up {len(stale)} stale session(s)")


def save_session(session_id, session):
    """Checkpoint session state to disk for cross-worker and crash recovery."""
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        data = {
            "comic_id": session.comic_id,
            "language": session.language,
            "state": session.state,
            "panels_data": session.panels_data,
            "strip_panel_count": len(session.comic_strip.panels) if session.comic_strip else 0,
        }
        path = os.path.join(SESSIONS_DIR, f"{session_id}.pkl")
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        print(f"[SESSION] Failed to save checkpoint: {e}")


def load_session_data(session_id):
    """Load raw session data from a disk checkpoint."""
    path = os.path.join(SESSIONS_DIR, f"{session_id}.pkl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        print(f"[SESSION] Failed to load checkpoint: {e}")
        return None


def recover_session(session_id):
    """Try to recover a session from a disk checkpoint."""
    data = load_session_data(session_id)
    if not data:
        return None
    try:
        # Recreate session (this rebuilds narratron, image_gen, etc.)
        session = ComicSession(data["comic_id"], language=data["language"])
        session.state = data["state"]
        session.panels_data = data["panels_data"]

        # Create an empty comic strip — it will be rebuilt fresh from
        # panels_data at finish time.  During gameplay submit_panel_streaming
        # adds to it, but those additions don't need to be perfect.
        session.comic_strip = ComicStrip(title=session.config.blueprint.title)

        print(f"[SESSION] Recovered session {session_id} ({len(data['panels_data'])} panels)")
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
    """Look up a session, always merging with disk to handle cross-worker routing."""
    session = sessions.get(session_id)

    if not session:
        # Not in this worker's memory — try to recover from disk
        session = recover_session(session_id)
        if session:
            sessions[session_id] = session
            touch_session(session_id)
        return session

    # Session is in memory, but another worker may have advanced it.
    # Always check disk and use whichever has more panels.
    disk_data = load_session_data(session_id)
    if disk_data:
        disk_panels = disk_data["panels_data"]
        if len(disk_panels) > len(session.panels_data):
            print(f"[SESSION] Disk has {len(disk_panels)} panels vs "
                  f"{len(session.panels_data)} in memory — using disk")
            session.panels_data = disk_panels
            session.state = disk_data["state"]

    touch_session(session_id)
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

    # get_session already merged disk data if another worker was ahead.

    # If the user typed text in the last interactive panel before clicking
    # Finish, attach it now so the panel gets included in the strip.
    final_input = (data.get("user_input") or "").strip()
    if final_input:
        for panel in reversed(session.panels_data):
            if (not panel.get("is_title_card")
                    and not panel.get("is_auto")
                    and panel.get("user_input_text") is None):
                panel["user_input_text"] = final_input
                break

    # Rebuild the comic strip from panels_data.  Include every panel
    # except the trailing unfilled interactive panel (the one the user
    # hasn't written in yet).
    panels_to_include = list(session.panels_data)
    if panels_to_include:
        last = panels_to_include[-1]
        if (not last.get("is_title_card")
                and not last.get("is_auto")
                and last.get("user_input_text") is None):
            panels_to_include.pop()

    session.comic_strip = ComicStrip(title=session.config.blueprint.title)
    for i, panel in enumerate(panels_to_include):
        has_image = panel.get("image_bytes") is not None
        print(f"  panel[{i}] pn={panel.get('panel_number')} "
              f"title_card={panel.get('is_title_card', False)} "
              f"auto={panel.get('is_auto', False)} "
              f"input={'yes' if panel.get('user_input_text') else 'no'} "
              f"has_image={has_image}")
        if has_image:
            session.comic_strip.add_panel(
                panel["image_bytes"],
                panel.get("user_input_text") or "",
                panel["panel_number"],
                elements=panel.get("elements"),
                user_input_text=panel.get("user_input_text"),
                detected_bubbles=panel.get("detected_bubbles"),
            )

    print(f"[FINISH] {session_id}: {len(session.panels_data)} in panels_data, "
          f"{session.comic_strip.get_panel_count()} added to strip")

    try:
        result = session.finish()
        sessions.pop(session_id, None)
        session_timestamps.pop(session_id, None)
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

    cleanup_stale_sessions()

    try:
        session = ComicSession(comic_id, language=language)
        sessions[session_id] = session
        touch_session(session_id)

        def generate():
            prev_count = len(session.panels_data)
            for event in session.start_streaming():
                # Checkpoint to disk whenever a panel is added so other
                # workers (and the finish endpoint) always see latest data.
                if len(session.panels_data) != prev_count:
                    save_session(session_id, session)
                    prev_count = len(session.panels_data)
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
        prev_count = len(session.panels_data)
        first_event = True
        for event in session.submit_panel_streaming(user_input_text):
            # Checkpoint to disk whenever state changes.  On the first
            # event, user_input_text has been set on the current panel.
            # On complete events, a new panel was appended.  Saving
            # BEFORE the yield ensures data survives connection drops
            # and is visible to other workers immediately.
            if first_event or len(session.panels_data) != prev_count:
                save_session(session_id, session)
                prev_count = len(session.panels_data)
                first_event = False
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
