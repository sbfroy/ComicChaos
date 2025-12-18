"""Image generation module for comic-style visuals."""

import os
import base64
import hashlib
import httpx
from pathlib import Path
from datetime import datetime

from openai import OpenAI

from ..state.game_state import RenderState


class ImageGenerator:
    """Generates comic-style images for the game."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "dall-e-3",
        output_dir: str | Path = "assets/generated",
        cache_enabled: bool = True
    ):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_enabled = cache_enabled
        self._cache: dict[str, str] = {}  # prompt_hash -> filepath
        self._last_image_path: str | None = None

    def _hash_prompt(self, prompt: str) -> str:
        """Create a hash of the prompt for caching."""
        return hashlib.md5(prompt.encode()).hexdigest()[:12]

    def _get_cached_image(self, prompt_hash: str) -> str | None:
        """Check if we have a cached image for this prompt."""
        if not self.cache_enabled:
            return None

        if prompt_hash in self._cache:
            path = self._cache[prompt_hash]
            if Path(path).exists():
                return path
            del self._cache[prompt_hash]

        # Check filesystem for cached images
        for img_path in self.output_dir.glob(f"{prompt_hash}_*.png"):
            self._cache[prompt_hash] = str(img_path)
            return str(img_path)

        return None

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str = "comic book style, vibrant colors, bold outlines, dramatic lighting",
        size: str = "1024x1024",
        quality: str = "standard"
    ) -> str | None:
        """
        Generate an image from the render state.

        Returns the path to the generated image or None if generation fails.
        """
        # Build the prompt
        prompt = self._build_prompt(render_state, visual_style)

        # Check cache
        prompt_hash = self._hash_prompt(prompt)
        cached = self._get_cached_image(prompt_hash)
        if cached:
            self._last_image_path = cached
            return cached

        try:
            # Generate the image
            response = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
                response_format="b64_json"
            )

            # Save the image
            image_data = response.data[0].b64_json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prompt_hash}_{timestamp}.png"
            filepath = self.output_dir / filename

            with open(filepath, "wb") as f:
                f.write(base64.b64decode(image_data))

            # Update cache
            self._cache[prompt_hash] = str(filepath)
            self._last_image_path = str(filepath)

            return str(filepath)

        except Exception as e:
            print(f"Image generation failed: {e}")
            return None

    def _build_prompt(self, render_state: RenderState, visual_style: str) -> str:
        """Build an image generation prompt from the render state."""
        parts = []

        # Style first
        parts.append(f"Art style: {visual_style}")

        # Scene/location
        if render_state.location_visual:
            parts.append(f"Scene: {render_state.location_visual}")

        # Time and weather atmosphere
        atmosphere_parts = []
        if render_state.time_of_day:
            atmosphere_parts.append(f"{render_state.time_of_day} time")
        if render_state.weather and render_state.weather != "clear":
            atmosphere_parts.append(f"{render_state.weather} weather")
        if atmosphere_parts:
            parts.append(f"Atmosphere: {', '.join(atmosphere_parts)}")

        # Characters in scene (limit to prevent prompt overflow)
        if render_state.characters_present:
            chars = render_state.characters_present[:2]  # Limit to 2 characters
            parts.append(f"Characters: {'; '.join(chars)}")

        # Current action
        if render_state.current_action:
            parts.append(f"Action: {render_state.current_action}")

        # Visible objects (limit)
        if render_state.objects_visible:
            objects = render_state.objects_visible[:3]
            parts.append(f"Notable objects: {', '.join(objects)}")

        # Mood
        if render_state.mood:
            mood_map = {
                "tense": "tense atmosphere, dramatic shadows",
                "calm": "peaceful atmosphere, soft lighting",
                "action": "dynamic action scene, motion blur effects",
                "mysterious": "mysterious atmosphere, fog, shadows",
                "humorous": "lighthearted comedic scene",
                "dramatic": "dramatic cinematic framing"
            }
            mood_desc = mood_map.get(render_state.mood, render_state.mood)
            parts.append(f"Mood: {mood_desc}")

        # Additional instructions
        parts.append("Single panel comic illustration, no speech bubbles, no text")

        # Join all parts
        full_prompt = ". ".join(parts)

        # Ensure prompt isn't too long (DALL-E has a 4000 char limit)
        if len(full_prompt) > 3800:
            full_prompt = full_prompt[:3800] + "..."

        return full_prompt

    def get_last_image_path(self) -> str | None:
        """Get the path of the most recently generated image."""
        return self._last_image_path

    def generate_from_prompt(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard"
    ) -> str | None:
        """Generate an image from a raw prompt string."""
        prompt_hash = self._hash_prompt(prompt)
        cached = self._get_cached_image(prompt_hash)
        if cached:
            self._last_image_path = cached
            return cached

        try:
            response = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=1,
                response_format="b64_json"
            )

            image_data = response.data[0].b64_json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prompt_hash}_{timestamp}.png"
            filepath = self.output_dir / filename

            with open(filepath, "wb") as f:
                f.write(base64.b64decode(image_data))

            self._cache[prompt_hash] = str(filepath)
            self._last_image_path = str(filepath)

            return str(filepath)

        except Exception as e:
            print(f"Image generation failed: {e}")
            return None

    def clear_cache(self) -> None:
        """Clear the image cache."""
        self._cache.clear()

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
                # Remove from cache if present
                for hash_key, cached_path in list(self._cache.items()):
                    if cached_path == str(img_path):
                        del self._cache[hash_key]
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
        quality: str = "standard"
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
