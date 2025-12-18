"""Simple web-based UI for the narrative game with image display."""

import json
import os
import subprocess
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Callable

from ..state.game_state import GameState
from ..state.static_config import StaticConfig


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def open_browser(url: str) -> None:
    """Open a URL in the default browser, handling WSL specially."""
    if is_wsl():
        try:
            # Try wslview first
            subprocess.run(["wslview", url], check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                # Fall back to cmd.exe
                subprocess.run(["cmd.exe", "/c", "start", url], check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                webbrowser.open(url)
    else:
        webbrowser.open(url)


class GameWebHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the game web interface."""

    game_state: GameState | None = None
    config: StaticConfig | None = None
    process_action: Callable | None = None
    current_narrative: str = ""
    current_image: str | None = None
    milestone_completed: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self.send_game_page()
        elif parsed.path == "/state":
            self.send_game_state()
        elif parsed.path.startswith("/assets/"):
            self.serve_asset()
        elif parsed.path == "/favicon.ico":
            # Ignore favicon requests
            self.send_response(204)
            self.end_headers()
        else:
            # For any other path, try to serve the main page
            self.send_game_page()

    def do_POST(self):
        if self.path == "/action":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)
            action = data.get("action", "")

            if action and GameWebHandler.process_action:
                result = GameWebHandler.process_action(action)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            else:
                self.send_error(400)
        else:
            self.send_error(404)

    def send_game_page(self):
        """Send the main game HTML page."""
        html = self.get_game_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def send_game_state(self):
        """Send current game state as JSON."""
        state = {
            "narrative": GameWebHandler.current_narrative,
            "image": GameWebHandler.current_image,
            "milestone": GameWebHandler.milestone_completed,
            "location": "",
            "turn": 0,
            "health": 100,
            "inventory": [],
            "progress": "0/0"
        }

        if GameWebHandler.game_state:
            gs = GameWebHandler.game_state
            location = GameWebHandler.config.get_location_by_id(gs.player.location_id) if GameWebHandler.config else None
            state["location"] = location.name if location else gs.player.location_id
            state["turn"] = gs.meta.turn_count
            state["health"] = gs.player.health
            state["inventory"] = gs.player.inventory
            state["scene"] = gs.narrative.current_scene

            if GameWebHandler.config:
                completed = len(gs.checkpoints.completed_milestones)
                total = len(GameWebHandler.config.milestones)
                state["progress"] = f"{completed}/{total}"

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(state).encode())

    def serve_asset(self):
        """Serve generated images."""
        from urllib.parse import unquote

        # Remove /assets/ prefix and strip query string
        file_path = self.path[8:].split("?")[0]
        file_path = unquote(file_path)  # Handle URL encoding
        full_path = Path("assets/generated") / file_path

        # Also try with just the filename in case full path was passed
        if not full_path.exists():
            full_path = Path("assets/generated") / Path(file_path).name

        if full_path.exists() and full_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".txt"):
            self.send_response(200)
            if full_path.suffix.lower() == ".png":
                content_type = "image/png"
            elif full_path.suffix.lower() in (".jpg", ".jpeg"):
                content_type = "image/jpeg"
            elif full_path.suffix.lower() == ".gif":
                content_type = "image/gif"
            else:
                content_type = "text/plain"
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(full_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            # Return a placeholder instead of 404
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Image not found")

    def get_game_html(self):
        """Generate the game HTML page."""
        title = "NARRATRON"
        if GameWebHandler.config and GameWebHandler.config.world_blueprint:
            title = GameWebHandler.config.world_blueprint.title

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - NARRATRON</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: 'Georgia', serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}

        .header {{
            background: #0f0f23;
            padding: 15px 20px;
            border-bottom: 2px solid #ffd700;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .header h1 {{
            color: #ffd700;
            font-size: 1.5rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }}

        .stats {{
            display: flex;
            gap: 20px;
            font-size: 0.9rem;
        }}

        .stat {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}

        .main-content {{
            flex: 1;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            padding: 20px;
            max-width: 1400px;
            margin: 0 auto;
            width: 100%;
        }}

        .comic-panel {{
            background: #0a0a1a;
            border: 4px solid #333;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }}

        .image-panel {{
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(45deg, #1a1a2e, #0a0a1a);
        }}

        .image-panel img {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }}

        .image-placeholder {{
            color: #555;
            font-style: italic;
            text-align: center;
            padding: 20px;
        }}

        .story-panel {{
            display: flex;
            flex-direction: column;
        }}

        .narrative {{
            flex: 1;
            padding: 20px;
            font-size: 1.1rem;
            line-height: 1.8;
            overflow-y: auto;
            max-height: 400px;
        }}

        .scene {{
            padding: 15px 20px;
            background: rgba(255,215,0,0.1);
            border-top: 1px solid #333;
            font-style: italic;
            color: #aaa;
        }}

        .milestone {{
            background: linear-gradient(90deg, #2d5016, #1a3009);
            padding: 15px 20px;
            text-align: center;
            border-bottom: 1px solid #4a7c23;
        }}

        .milestone-text {{
            color: #7fff00;
            font-weight: bold;
        }}

        .input-area {{
            background: #0f0f23;
            padding: 20px;
            border-top: 2px solid #333;
        }}

        .input-container {{
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            gap: 10px;
        }}

        #action-input {{
            flex: 1;
            padding: 15px 20px;
            font-size: 1rem;
            background: #1a1a2e;
            border: 2px solid #333;
            border-radius: 8px;
            color: #e0e0e0;
            font-family: inherit;
        }}

        #action-input:focus {{
            outline: none;
            border-color: #ffd700;
        }}

        #action-input::placeholder {{
            color: #666;
        }}

        .submit-btn {{
            padding: 15px 30px;
            font-size: 1rem;
            background: linear-gradient(135deg, #ffd700, #ffaa00);
            border: none;
            border-radius: 8px;
            color: #1a1a2e;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .submit-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(255,215,0,0.3);
        }}

        .submit-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }}

        .loading {{
            display: none;
            color: #ffd700;
            padding: 10px;
            text-align: center;
        }}

        .loading.active {{
            display: block;
        }}

        @media (max-width: 900px) {{
            .main-content {{
                grid-template-columns: 1fr;
            }}

            .image-panel {{
                aspect-ratio: 16/9;
            }}
        }}
    </style>
</head>
<body>
    <header class="header">
        <h1>📖 {title}</h1>
        <div class="stats">
            <div class="stat">📍 <span id="location">Loading...</span></div>
            <div class="stat">❤️ <span id="health">100</span>%</div>
            <div class="stat">⭐ <span id="progress">0/0</span></div>
            <div class="stat">🎯 Turn <span id="turn">0</span></div>
        </div>
    </header>

    <main class="main-content">
        <div class="comic-panel image-panel" id="image-container">
            <div class="image-placeholder">
                <p>🎨 Scene illustrations will appear here</p>
                <p style="font-size: 0.8rem; margin-top: 10px;">Enter an action to begin...</p>
            </div>
        </div>

        <div class="comic-panel story-panel">
            <div id="milestone-banner" class="milestone" style="display: none;">
                <span class="milestone-text">✨ <span id="milestone-text"></span> ✨</span>
            </div>
            <div class="narrative" id="narrative">
                <p>Welcome to the adventure. Type an action below to begin your story...</p>
            </div>
            <div class="scene" id="scene"></div>
        </div>
    </main>

    <div class="input-area">
        <div class="loading" id="loading">Processing your action...</div>
        <form class="input-container" id="action-form">
            <input type="text" id="action-input" placeholder="What do you do? (e.g., look around, talk to Vivian, go north...)" autocomplete="off">
            <button type="submit" class="submit-btn" id="submit-btn">Act</button>
        </form>
    </div>

    <script>
        const form = document.getElementById('action-form');
        const input = document.getElementById('action-input');
        const submitBtn = document.getElementById('submit-btn');
        const loading = document.getElementById('loading');
        const narrative = document.getElementById('narrative');
        const scene = document.getElementById('scene');
        const imageContainer = document.getElementById('image-container');
        const milestoneBanner = document.getElementById('milestone-banner');
        const milestoneText = document.getElementById('milestone-text');

        // Load initial state
        fetchState();

        form.addEventListener('submit', async (e) => {{
            e.preventDefault();
            const action = input.value.trim();
            if (!action) return;

            submitBtn.disabled = true;
            loading.classList.add('active');
            input.value = '';

            try {{
                const response = await fetch('/action', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ action }})
                }});

                if (response.ok) {{
                    await fetchState();
                }}
            }} catch (error) {{
                console.error('Error:', error);
            }} finally {{
                submitBtn.disabled = false;
                loading.classList.remove('active');
                input.focus();
            }}
        }});

        async function fetchState() {{
            try {{
                const response = await fetch('/state');
                const state = await response.json();

                // Update stats
                document.getElementById('location').textContent = state.location || 'Unknown';
                document.getElementById('health').textContent = state.health || 100;
                document.getElementById('progress').textContent = state.progress || '0/0';
                document.getElementById('turn').textContent = state.turn || 0;

                // Update narrative
                if (state.narrative) {{
                    narrative.innerHTML = '<p>' + state.narrative.replace(/\\n/g, '</p><p>') + '</p>';
                }}

                // Update scene
                if (state.scene) {{
                    scene.textContent = state.scene;
                    scene.style.display = 'block';
                }}

                // Update image
                if (state.image) {{
                    const imgPath = '/assets/' + state.image.split('/').pop();
                    imageContainer.innerHTML = '<img src="' + imgPath + '?' + Date.now() + '" alt="Scene illustration">';
                }}

                // Show milestone banner
                if (state.milestone) {{
                    milestoneText.textContent = state.milestone;
                    milestoneBanner.style.display = 'block';
                    setTimeout(() => {{ milestoneBanner.style.display = 'none'; }}, 5000);
                }}
            }} catch (error) {{
                console.error('Error fetching state:', error);
            }}
        }}

        // Auto-refresh every 2 seconds to catch image updates
        setInterval(fetchState, 2000);
    </script>
</body>
</html>'''

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


class WebUI:
    """Web-based UI manager."""

    def __init__(self, config: StaticConfig, port: int = 8080):
        self.config = config
        self.port = port
        self.server: HTTPServer | None = None
        self.server_thread: threading.Thread | None = None

        # Set class variables for handler
        GameWebHandler.config = config

    def start(self, game_state: GameState, process_action: Callable) -> None:
        """Start the web server."""
        GameWebHandler.game_state = game_state
        GameWebHandler.process_action = process_action

        self.server = HTTPServer(("localhost", self.port), GameWebHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

        url = f"http://localhost:{self.port}"
        print(f"\n🌐 Web UI started at: {url}")
        print("   Opening in your browser...")
        open_browser(url)

    def update(
        self,
        narrative: str,
        image_path: str | None = None,
        milestone_completed: str | None = None
    ) -> None:
        """Update the displayed content."""
        GameWebHandler.current_narrative = narrative
        GameWebHandler.current_image = image_path
        GameWebHandler.milestone_completed = milestone_completed

    def stop(self) -> None:
        """Stop the web server."""
        if self.server:
            self.server.shutdown()
