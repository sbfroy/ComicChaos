"""Image generation module for comic-style visuals."""

import os
import base64
from pathlib import Path
from datetime import datetime

from openai import OpenAI

from ..config import (
    IMAGE_MODEL,
    IMAGE_SIZE,
    IMAGE_QUALITY,
    IMAGE_MODERATION,
    GENERATED_IMAGES_DIR,
)
from ..state.comic_state import RenderState


class ImageGenerator:
    """Generates comic-style images for the game."""

    def __init__(self, api_key: str | None = None):
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.output_dir = Path(GENERATED_IMAGES_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str
    ) -> str | None:
        """
        Generate an image from the render state.

        Returns the path to the generated image or None if generation fails.
        """
        # Build the prompt
        prompt = self._build_prompt(render_state, visual_style)

        try:
            result = self.client.images.generate(
                model=IMAGE_MODEL,
                prompt=prompt,
                size=IMAGE_SIZE,
                quality=IMAGE_QUALITY,
                moderation=IMAGE_MODERATION,
            )

            # TODO: Maybe save the images only for a moment, and once they are saved as a comic strip,
            # delete the individual images to save space.

            # TODO: Fix sizing issues. Final comic strip looks off.

            image_base64 = result.data[0].b64_json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"image_{timestamp}.png"
            filepath = self.output_dir / filename

            # Decode and save image
            img_bytes = base64.b64decode(image_base64)
            with open(filepath, "wb") as f:
                f.write(img_bytes)

            return str(filepath)

        except Exception as e:
            print(f"Image generation failed: {e}")
            return None

    def _build_prompt(self, render_state: RenderState, visual_style: str) -> str:
        """Build an image generation prompt from the render state."""
        parts = []

        # Visual style first (applies to entire comic)
        parts.append(f"{visual_style}")

        # Scene/location
        if render_state.scene_setting:
            parts.append(f"Setting: {render_state.scene_setting}")

        # Characters in scene
        if render_state.characters_present:
            for char in render_state.characters_present:
                parts.append(f"Character: {char}")

        # Current action
        if render_state.current_action:
            parts.append(f"Action: {render_state.current_action}")

        # Join all parts
        full_prompt = ". ".join(parts)

        return full_prompt


class MockImageGenerator(ImageGenerator):
    """A mock image generator for testing without API calls."""

    def __init__(self):
        self.output_dir = Path(GENERATED_IMAGES_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._call_count = 0

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str = "comic book style"
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
            f.write(f"Size: {IMAGE_SIZE}\n")
            f.write(f"Quality: {IMAGE_QUALITY}\n")

        return str(filepath)
