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
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from openai import OpenAI
from PIL import Image

from ..config import (
    IMAGE_MODEL,
    IMAGE_SIZE,
    IMAGE_QUALITY,
    IMAGE_MODERATION,
    GENERATED_IMAGES_DIR,
)
from ..state.comic_state import RenderState
from ..logging.interaction_logger import InteractionLogger
from .bubble_detector import BubbleDetector, DetectedBubble
from .text_renderer import TextRenderer, TextElement


class ImageGenerator:
    """Generates comic-style images for the comic.

    This class uses OpenAI's API to generate images based on the comic's
    render state and visual style. Generated images are saved to the configured
    output directory. It can also detect empty bubbles in generated images
    and render text into them.

    Attributes:
        client: OpenAI client for making API calls.
        output_dir: Path to the directory where generated images are saved.
        bubble_detector: Detector for finding empty speech bubbles.
        text_renderer: Renderer for adding text to bubbles.
    """

    def __init__(self, api_key: Optional[str] = None, logger: Optional[InteractionLogger] = None) -> None:
        """Initialize the image generator.

        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY environment variable.
            logger: Interaction logger for tracking prompts and responses.
        """
        self.client: OpenAI = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )
        self.output_dir: Path = Path(GENERATED_IMAGES_DIR)
        # Ensure output directory exists, create if necessary
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger: Optional[InteractionLogger] = logger

        # Initialize bubble detection and text rendering
        self.bubble_detector = BubbleDetector()
        self.text_renderer = TextRenderer()

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str,
        elements: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Generate an image from the render state.

        Builds a detailed prompt from the render state and visual style,
        then calls the API to generate the image. If elements are provided,
        the prompt will request empty speech bubbles (but text is NOT
        rendered - that happens when generating the final comic strip).

        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
            elements: Optional list of element dictionaries for bubble generation.

        Returns:
            The absolute path to the generated image file, or None if generation fails.
        """
        # Build the detailed prompt from render state and visual style
        prompt = self._build_prompt(render_state, visual_style, elements)

        try:
            # Call API to generate the image
            result = self.client.images.generate(
                model=IMAGE_MODEL,
                prompt=prompt,
                size=IMAGE_SIZE,
                quality=IMAGE_QUALITY,
                moderation=IMAGE_MODERATION,
            )

            # Extract base64-encoded image data from response
            image_base64 = result.data[0].b64_json

            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"image_{timestamp}.png"
            filepath = self.output_dir / filename

            # Decode base64 image data and save to file
            image_bytes = base64.b64decode(image_base64)
            with open(filepath, "wb") as file:
                file.write(image_bytes)

            # Log successful generation
            if self.logger:
                self.logger.log_image_generation(
                    prompt=prompt,
                    image_path=str(filepath),
                    model=IMAGE_MODEL,
                    size=IMAGE_SIZE,
                    quality=IMAGE_QUALITY,
                    success=True
                )

            return str(filepath)

        except Exception as error:
            # Log error and return None on failure
            print(f"Image generation failed: {error}")

            # Log failed generation
            if self.logger:
                self.logger.log_image_generation(
                    prompt=prompt,
                    image_path=None,
                    model=IMAGE_MODEL,
                    size=IMAGE_SIZE,
                    quality=IMAGE_QUALITY,
                    success=False,
                    error_message=str(error)
                )

            return None

    def process_bubbles(
        self,
        image_path: str,
        elements: List[Dict[str, Any]],
        user_input_text: Optional[str] = None,
    ) -> Optional[str]:
        """Detect bubbles in an image and render text into them.

        This is called when generating the final comic strip to bake
        text into the bubble regions.

        Args:
            image_path: Path to the image with empty bubbles.
            elements: List of element dictionaries with text to render.
            user_input_text: The text the user entered for the user_input element.

        Returns:
            Path to the processed image, or None if processing fails.
        """
        try:
            # Detect bubbles in the image
            bubbles = self.bubble_detector.detect_bubbles(image_path)

            if not bubbles:
                print("No bubbles detected in image")
                return image_path  # Return original if no bubbles found

            # Convert elements to TextElement objects
            text_elements = []
            for el in elements:
                el_type = el.get("type", "")

                # Determine the text content
                if el.get("user_input"):
                    # Use the actual user input for this element
                    text = user_input_text or ""
                else:
                    text = el.get("text", "")

                # Skip elements without text
                if not text:
                    continue

                text_elements.append(TextElement(
                    text=text,
                    element_type=el_type,
                    character_name=el.get("character_name"),
                ))

            if not text_elements:
                return image_path

            # Load image and render text
            img = Image.open(image_path)
            processed_img = self.text_renderer.render_all_bubbles(
                img, bubbles, text_elements
            )

            # Save processed image with _final suffix
            original_path = Path(image_path)
            processed_filename = original_path.stem + "_final" + original_path.suffix
            processed_filepath = original_path.parent / processed_filename
            processed_img.save(processed_filepath)

            return str(processed_filepath)

        except Exception as error:
            print(f"Bubble processing failed: {error}")
            return image_path  # Return original image on failure

    def _build_prompt(
        self,
        render_state: RenderState,
        visual_style: str,
        elements: Optional[List[Dict[str, Any]]] = None,
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

        # Add all characters present in the scene
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

        # Add instruction to not include borders
        prompt_parts.append("No borders, no frames, no panel edges.")

        # Join all parts into a coherent prompt
        full_prompt = " ".join(prompt_parts)

        return full_prompt

    def _build_bubble_instructions(self, elements: List[Dict[str, Any]]) -> str:
        """Build instructions for generating ONE empty speech bubble.

        Only generates a bubble for the user_input element. Pre-filled
        elements will use HTML overlays or programmatic drawing.

        Args:
            elements: List of elements that need speech bubbles.

        Returns:
            Instruction string for the image generation prompt.
        """
        # Find the user_input element
        user_input_el = None
        for el in elements:
            if el.get("user_input"):
                user_input_el = el
                break

        if not user_input_el:
            return ""

        el_type = user_input_el.get("type", "speech")
        position = user_input_el.get("position", "center")

        # Map position to natural language
        position_hints = {
            "top-left": "in the upper left area",
            "top-center": "at the top",
            "top-right": "in the upper right area",
            "center-left": "on the left side",
            "center": "in the center",
            "center-right": "on the right side",
            "bottom-left": "in the lower left area",
            "bottom-center": "at the bottom",
            "bottom-right": "in the lower right area",
        }
        position_hint = position_hints.get(position, "")

        # Build bubble instruction for just the user input element
        if el_type == "speech":
            bubble_desc = (
                f"Include ONE empty white oval speech bubble with black outline and a pointed tail "
                f"{position_hint}. The bubble should be large enough to contain a short sentence, "
                "completely empty inside with no text whatsoever."
            )
        elif el_type == "thought":
            bubble_desc = (
                f"Include ONE empty white cloud-shaped thought bubble with small circular tail dots "
                f"{position_hint}. The bubble should be large enough to contain a short thought, "
                "completely empty inside with no text whatsoever."
            )
        elif el_type == "narration":
            bubble_desc = (
                f"Include ONE empty rectangular caption box with yellow/cream background "
                f"{position_hint}. The box should be large enough to contain narration text, "
                "completely empty inside with no text whatsoever."
            )
        else:
            # SFX or unknown - no bubble needed
            return ""

        return bubble_desc


class MockImageGenerator(ImageGenerator):
    """A mock image generator for testing without API calls.

    This class provides a testing alternative to the real ImageGenerator.
    Instead of making actual API calls, it creates text files containing
    the prompt and configuration that would have been sent to the API.

    Attributes:
        output_dir: Path to the directory where mock files are saved.
        _call_count: Counter tracking the number of generation calls.
    """

    def __init__(self) -> None:
        """Initialize the mock image generator.

        Note: Does not call parent __init__ to avoid creating an OpenAI client.
        """
        self.output_dir: Path = Path(GENERATED_IMAGES_DIR)
        # Ensure output directory exists, create if necessary
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._call_count: int = 0

    def generate_image(
        self,
        render_state: RenderState,
        visual_style: str = "comic book style",
        elements: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Generate a mock image without making API calls.

        Creates a text file documenting what would have been sent to the API,
        useful for testing and debugging without incurring API costs.

        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
            elements: Optional list of element dictionaries with text to render.

        Returns:
            The absolute path to the generated text file.
        """
        # Increment call counter for unique filenames
        self._call_count += 1

        # Build the prompt that would be sent to the API
        prompt = self._build_prompt(render_state, visual_style, elements)

        # Generate unique filename with call count and timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mock_{self._call_count}_{timestamp}.txt"
        filepath = self.output_dir / filename

        # Create a text file documenting the mock generation
        with open(filepath, "w") as file:
            file.write("MOCK IMAGE GENERATION\n")
            file.write("=====================\n\n")
            file.write(f"Prompt:\n{prompt}\n\n")
            file.write(f"Size: {IMAGE_SIZE}\n")
            file.write(f"Quality: {IMAGE_QUALITY}\n")
            if elements:
                file.write(f"\nElements:\n")
                for i, el in enumerate(elements):
                    file.write(f"  {i+1}. {el.get('type', 'unknown')}: {el.get('text', el.get('placeholder', ''))}\n")

        return str(filepath)
