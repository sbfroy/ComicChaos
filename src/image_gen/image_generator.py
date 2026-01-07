"""Image generation module for comic-style visuals."""

import os
import base64
import hashlib
import httpx
from pathlib import Path
from datetime import datetime

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

from ..state.game_state import RenderState


class ImageGenerator:
    """Generates comic-style images for the game."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-image-1-mini",  # "dall-e-3"
        output_dir: str | Path = "assets/generated",
        verbose: bool = False
    ):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self._console = Console() if verbose else None
        self._last_image_path: str | None = None

    def _log(self, title: str, content: str, style: str = "dim") -> None:
        """Log verbose output if enabled."""
        if not self.verbose or not self._console:
            return
        self._console.print(Panel(content, title=f"[bold]{title}[/bold]", border_style=style))

    def _log_section(self, text: str, style: str = "yellow") -> None:
        """Log a section header."""
        if not self.verbose or not self._console:
            return
        self._console.print(f"\n[{style}]{'='*60}[/{style}]")
        self._console.print(f"[{style} bold]{text}[/{style} bold]")
        self._console.print(f"[{style}]{'='*60}[/{style}]\n")

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str = "comic book style, vibrant colors, bold outlines, dramatic lighting",
        size: str = "1024x1024",
        quality: str = "auto"
    ) -> str | None:
        """
        Generate an image from the render state.

        Returns the path to the generated image or None if generation fails.
        """
        if self.verbose:
            self._log_section("IMAGE GENERATION", "magenta")

        # Build the prompt
        prompt = self._build_prompt(render_state, visual_style)

        if self.verbose:
            self._log("DALL-E Prompt", prompt, style="blue")

        if self.verbose and self._console:
            self._console.print(f"[dim]Calling {self.model} API (size={size}, quality={quality})...[/dim]")

        try:
            # Generate the image
            response = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
                #response_format="b64_json"
            )

            # Save the image
            image_data = response.data[0].b64_json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"panel_{timestamp}.png"
            filepath = self.output_dir / filename

            # Decode and save image
            img_bytes = base64.b64decode(image_data)
            with open(filepath, "wb") as f:
                f.write(img_bytes)

            self._last_image_path = str(filepath)

            if self.verbose and self._console:
                self._console.print(f"[green]Image generated![/green] Saved to: {filepath}\n")

            return str(filepath)

        except Exception as e:
            if self.verbose and self._console:
                self._console.print(f"[red]Image generation failed: {e}[/red]\n")
            else:
                print(f"Image generation failed: {e}")
            return None

    def _build_prompt(self, render_state: RenderState, visual_style: str) -> str:
        """Build an image generation prompt from the render state."""
        parts = []

        # Style first - keep it simple
        parts.append(f"{visual_style}")

        # Scene/location - simplified
        if render_state.location_visual:
            # Simplify the location description
            loc = render_state.location_visual
            if len(loc) > 100:
                loc = loc[:100]
            parts.append(f"Setting: {loc}")

        # TODO: Remove this stupid shit
        
        # Characters in scene (limit to 1-2 for simplicity)
        if render_state.characters_present:
            # Take just the first character for simpler images
            char = render_state.characters_present[0] if render_state.characters_present else ""
            if char and len(char) > 80:
                char = char[:80]
            if char:
                parts.append(f"Character: {char}")

        # Current action - keep simple
        if render_state.current_action:
            action = render_state.current_action
            if len(action) > 60:
                action = action[:60]
            parts.append(f"Action: {action}")

        # Simple mood mapping
        if render_state.mood:
            simple_moods = {
                "tense": "slightly worried",
                "calm": "peaceful",
                "action": "energetic",
                "mysterious": "curious",
                "humorous": "cheerful and funny",
                "dramatic": "expressive",
                "funny": "cheerful and silly",
                "peaceful": "calm and happy",
                "chaotic": "playful chaos"
            }
            mood_desc = simple_moods.get(render_state.mood, render_state.mood)
            parts.append(f"Mood: {mood_desc}")

        # Keep instructions simple
        parts.append("Simple single panel illustration, no text, no speech bubbles, clean composition")

        # Join all parts
        full_prompt = ". ".join(parts)

        # Ensure prompt isn't too long
        if len(full_prompt) > 2000:
            full_prompt = full_prompt[:2000]

        return full_prompt

    def get_last_image_path(self) -> str | None:
        """Get the path of the most recently generated image."""
        return self._last_image_path

    def generate_from_prompt(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "auto"
    ) -> str | None:
        """Generate an image from a raw prompt string."""
        try:
            response = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
                #response_format="b64_json"
            )

            image_data = response.data[0].b64_json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"prompt_{timestamp}.png"
            filepath = self.output_dir / filename

            with open(filepath, "wb") as f:
                f.write(base64.b64decode(image_data))

            self._last_image_path = str(filepath)

            return str(filepath)

        except Exception as e:
            print(f"Image generation failed: {e}")
            return None

    def cleanup_old_images(self, keep_count: int = 50) -> None:
        """Remove old generated images, keeping the most recent ones."""
        images = sorted(
            self.output_dir.glob("*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for img_path in images[keep_count:]:
            try:
                img_path.unlink()
            except Exception:
                pass


class MockImageGenerator(ImageGenerator):
    """A mock image generator for testing without API calls."""

    def __init__(self, output_dir: str | Path = "assets/generated"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._last_image_path: str | None = None
        self._call_count = 0

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str = "comic book style",
        size: str = "1024x1024",
        quality: str = "auto"
    ) -> str | None:
        """Return a placeholder path without making API calls."""
        self._call_count += 1
        prompt = self._build_prompt(render_state, visual_style)

        # Create a text file with the prompt for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mock_{self._call_count}_{timestamp}.txt"
        filepath = self.output_dir / filename

        with open(filepath, "w") as f:
            f.write(f"MOCK IMAGE GENERATION\n")
            f.write(f"=====================\n\n")
            f.write(f"Prompt:\n{prompt}\n\n")
            f.write(f"Size: {size}\n")
            f.write(f"Quality: {quality}\n")

        self._last_image_path = str(filepath)
        return str(filepath)

    def _build_prompt(self, render_state: RenderState, visual_style: str) -> str:
        """Use parent's prompt builder."""
        return super()._build_prompt(render_state, visual_style)
