"""Image generation module for comic-style visuals.

This module provides image generation capabilities for creating comic panels
using OpenAI's API. It includes both a production image generator and
a mock generator for testing purposes.

Classes:
    ImageGenerator: Generates comic-style images using the OpenAI API.
    MockImageGenerator: Mock generator for testing without API calls.
"""

import base64
import os
from typing import Optional, List, Dict, Any, Generator

from openai import OpenAI

from ..state.comic_state import RenderState
from ..state.static_config import ComicConfig
from ..logging.interaction_logger import InteractionLogger
from .panel_detector import PanelDetector


class ImageGenerator:
    """Generates comic-style images for the comic.

    This class uses OpenAI's API to generate images based on the comic's
    render state and visual style. Generated images are saved to the configured
    output directory. It can also detect empty bubbles in generated images
    and render text into them.

    Attributes:
        client: OpenAI client for making API calls.
        output_dir: Path to the directory where generated images are saved.
        panel_detector: Detector for finding empty speech bubbles and narration boxes.
        text_renderer: Renderer for adding text to bubbles.
    """

    def __init__(
        self,
        comic_config: Optional[ComicConfig] = None,
        api_key: Optional[str] = None,
        logger: Optional[InteractionLogger] = None,
    ) -> None:
        """Initialize the image generator.

        Args:
            comic_config: Per-comic configuration for model settings.
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY environment variable.
            logger: Interaction logger for tracking prompts and responses.
        """
        self.comic_config: ComicConfig = comic_config or ComicConfig()
        self.client: OpenAI = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )
        self.logger: Optional[InteractionLogger] = logger

        # Initialize panel element detection
        self.panel_detector = PanelDetector()

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str,
        elements: Optional[List[Dict[str, Any]]] = None,
        main_character_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate an image from the render state.

        Builds a detailed prompt from the render state and visual style,
        then calls the API to generate the image. After generation,
        detects bubble regions and returns their positions.

        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
            elements: Optional list of element dictionaries for bubble generation.

        Returns:
            Dictionary with:
                - image_bytes: Raw PNG bytes (or None on failure)
                - detected_bubbles: List of bubble position dicts with x, y, width, height
        """
        # Build the detailed prompt from render state and visual style
        prompt = self._build_prompt(render_state, visual_style, elements, main_character_description)

        try:
            # Call API to generate the image
            result = self.client.images.generate(
                model=self.comic_config.image_model,
                prompt=prompt,
                size=self.comic_config.image_size,
                quality=self.comic_config.image_quality,
                moderation=self.comic_config.image_moderation,
            )

            # Extract base64-encoded image data from response
            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)

            # Detect bubbles/boxes in the generated image
            detected_bubbles = []
            if elements:
                el_type = elements[0].get("type", "") if elements else ""
                if el_type == "narration":
                    bubbles = self.panel_detector.detect_narration_boxes(image_bytes)
                else:
                    bubbles = self.panel_detector.detect_bubbles(image_bytes)
                for bubble in bubbles:
                    detected_bubbles.append({
                        "x": bubble.x,
                        "y": bubble.y,
                        "width": bubble.width,
                        "height": bubble.height,
                        "center_x": bubble.center_x,
                        "center_y": bubble.center_y,
                    })

            # Log successful generation
            if self.logger:
                self.logger.log_image_generation(
                    prompt=prompt,
                    image_path=None,
                    model=self.comic_config.image_model,
                    size=self.comic_config.image_size,
                    quality=self.comic_config.image_quality,
                    success=True
                )

            return {
                "image_bytes": image_bytes,
                "detected_bubbles": detected_bubbles,
            }

        except Exception as error:
            # Log error and return None on failure
            print(f"Image generation failed: {error}")

            # Log failed generation
            if self.logger:
                self.logger.log_image_generation(
                    prompt=prompt,
                    image_path=None,
                    model=self.comic_config.image_model,
                    size=self.comic_config.image_size,
                    quality=self.comic_config.image_quality,
                    success=False,
                    error_message=str(error)
                )

            return {
                "image_bytes": None,
                "detected_bubbles": [],
            }

    def generate_image_streaming(
        self,
        render_state: RenderState,
        visual_style: str,
        elements: Optional[List[Dict[str, Any]]] = None,
        partial_images: int = 2,
        main_character_description: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Generate an image with streaming partial images.

        Yields partial images as they are generated, then the final image
        with bubble detection.

        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
            elements: Optional list of element dictionaries for bubble generation.
            partial_images: Number of partial images to generate (0-3).

        Yields:
            Dictionary with:
                - type: "partial" or "complete"
                - image_base64: Base64-encoded image data
                - partial_index: Index of partial image (for partial type)
                - image_bytes: Raw PNG bytes (for complete type)
                - detected_bubbles: List of bubble positions (for complete type)
        """
        prompt = self._build_prompt(render_state, visual_style, elements, main_character_description)

        try:
            stream = self.client.images.generate(
                model=self.comic_config.image_model,
                prompt=prompt,
                size=self.comic_config.image_size,
                quality=self.comic_config.image_quality,
                moderation=self.comic_config.image_moderation,
                stream=True,
                partial_images=partial_images,
            )

            final_image_base64 = None

            for event in stream:
                if event.type == "image_generation.partial_image":
                    yield {
                        "type": "partial",
                        "image_base64": event.b64_json,
                        "partial_index": event.partial_image_index,
                    }
                elif event.type == "image_generation.completed":
                    final_image_base64 = event.b64_json

            if final_image_base64:
                image_bytes = base64.b64decode(final_image_base64)

                # Detect bubbles/boxes
                detected_bubbles = []
                if elements:
                    el_type = elements[0].get("type", "") if elements else ""
                    if el_type == "narration":
                        bubbles = self.panel_detector.detect_narration_boxes(image_bytes)
                    else:
                        bubbles = self.panel_detector.detect_bubbles(image_bytes)
                    for bubble in bubbles:
                        detected_bubbles.append({
                            "x": bubble.x,
                            "y": bubble.y,
                            "width": bubble.width,
                            "height": bubble.height,
                            "center_x": bubble.center_x,
                            "center_y": bubble.center_y,
                        })

                # Log successful generation
                if self.logger:
                    self.logger.log_image_generation(
                        prompt=prompt,
                        image_path=None,
                        model=self.comic_config.image_model,
                        size=self.comic_config.image_size,
                        quality=self.comic_config.image_quality,
                        success=True
                    )

                yield {
                    "type": "complete",
                    "image_base64": final_image_base64,
                    "image_bytes": image_bytes,
                    "detected_bubbles": detected_bubbles,
                }

        except Exception as error:
            print(f"Streaming image generation failed: {error}")
            if self.logger:
                self.logger.log_image_generation(
                    prompt=prompt,
                    image_path=None,
                    model=self.comic_config.image_model,
                    size=self.comic_config.image_size,
                    quality=self.comic_config.image_quality,
                    success=False,
                    error_message=str(error)
                )
            yield {
                "type": "error",
                "error": str(error),
            }

    def _build_prompt(
        self,
        render_state: RenderState,
        visual_style: str,
        elements: Optional[List[Dict[str, Any]]] = None,
        main_character_description: Optional[str] = None,
    ) -> str:
        """Build an image generation prompt from the render state.

        Constructs a detailed prompt by combining the visual style, scene setting,
        characters present, and current action. If elements are provided, includes
        instructions to add empty speech bubbles.

        Args:
            render_state: The current render state with scene information.
            visual_style: The visual style description for the comic.
            elements: Optional list of elements that need speech bubbles.

        Returns:
            A formatted prompt string for image generation.
        """
        prompt_parts: List[str] = []

        # Start with visual style (applies to the entire comic)
        prompt_parts.append(f"Visual style: {visual_style}")

        # Add scene/location setting
        if render_state.scene_setting:
            prompt_parts.append(f"Setting: {render_state.scene_setting}")

        # Always include the main character's full description from the blueprint
        if main_character_description:
            prompt_parts.append(f"Main character: {main_character_description}")

        # Add other characters present in the scene
        if render_state.characters_present:
            for character in render_state.characters_present:
                prompt_parts.append(f"Character: {character}")

        # Add the current action happening in the panel
        if render_state.current_action:
            prompt_parts.append(f"Action: {render_state.current_action}")

        # Add bubble instructions if elements are provided
        if elements:
            bubble_instructions = self._build_bubble_instructions(elements)
            if bubble_instructions:
                prompt_parts.append(bubble_instructions)

        # Add instruction to not include frames or panel edges
        prompt_parts.append("No frames and no panel edges.")

        # Join all parts into a coherent prompt
        full_prompt = " ".join(prompt_parts)

        return full_prompt

    def _build_bubble_instructions(self, elements: List[Dict[str, Any]]) -> str:
        """Build instructions for generating ONE empty bubble or narration box.

        Generates bubble/box instructions for speech, thought, and narration elements.

        Args:
            elements: List of elements (should be exactly one).

        Returns:
            Instruction string for the image generation prompt.
        """
        if not elements:
            return ""

        # Get the single element
        el = elements[0]
        el_type = el.get("type", "")

        if el_type == "speech":
            return (
                "Include ONE empty white oval speech bubble with a black outline and a pointed tail, "
                "positioned near the main character, but inset slightly from the image edges "
                "(the bubble must not touch or go over the edges). "
                "The bubble should be large enough to contain "
                "a sentence, completely empty inside with no text. The entire bubble must be visible."
            )
        elif el_type == "thought":
            return (
                "Include ONE empty white cloud-shaped thought bubble with small circular tail dots, "
                "positioned near the main character's head, but inset slightly from the image edges "
                "(the bubble must not touch or go over the edges). "
                "The bubble should be large enough to "
                "contain a thought, completely empty inside with no text. The entire bubble must be visible."
            )
        elif el_type == "narration":
            return (
                "Include ONE empty rectangular white narration box with a black outline, "
                "positioned in one of the corners, but inset slightly from the image edges "
                "(the box must not touch the edges). "
                "The box should be roughly two-thirds of the image width and tall enough for "
                "2–3 lines of text. Completely empty inside with no text. "
                "The box must have sharp 90-degree corners (not rounded)."
            )

        return ""


class MockImageGenerator(ImageGenerator):
    """A mock image generator for testing without API calls.

    This class provides a testing alternative to the real ImageGenerator.
    Instead of making actual API calls, it returns empty image bytes.

    Attributes:
        _call_count: Counter tracking the number of generation calls.
    """

    def __init__(self) -> None:
        """Initialize the mock image generator.

        Note: Does not call parent __init__ to avoid creating an OpenAI client.
        """
        self.comic_config: ComicConfig = ComicConfig()
        self._call_count: int = 0

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str = "comic book style",
        elements: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate a mock image without making API calls.

        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
            elements: Optional list of element dictionaries with text to render.

        Returns:
            Dictionary with image_bytes and empty detected_bubbles list.
        """
        self._call_count += 1

        return {
            "image_bytes": None,
            "detected_bubbles": [],
        }
