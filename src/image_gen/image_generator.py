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
from typing import Optional, List

from openai import OpenAI

from ..config import (
    IMAGE_MODEL,
    IMAGE_SIZE,
    IMAGE_QUALITY,
    IMAGE_MODERATION,
    GENERATED_IMAGES_DIR,
)
from ..state.comic_state import RenderState
from ..logging.interaction_logger import InteractionLogger


class ImageGenerator:
    """Generates comic-style images for the comic.
    
    This class uses OpenAI's API to generate images based on the comic's
    render state and visual style. Generated images are saved to the configured
    output directory.
    
    Attributes:
        client: OpenAI client for making API calls.
        output_dir: Path to the directory where generated images are saved.
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

    def generate_image(
        self, render_state: RenderState, visual_style: str
    ) -> Optional[str]:
        """Generate an image from the render state.
        
        Builds a detailed prompt from the render state and visual style,
        then calls the API to generate the image. The image is saved
        to the output directory with a timestamp-based filename.
        
        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
        
        Returns:
            The absolute path to the generated image file, or None if generation fails.
        """
        # Build the detailed prompt from render state and visual style
        prompt = self._build_prompt(render_state, visual_style)

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

    def _build_prompt(self, render_state: RenderState, visual_style: str) -> str:
        """Build an image generation prompt from the render state.
        
        Constructs a detailed prompt by combining the visual style, scene setting,
        characters present, and current action. The prompt is structured to give
        the image generation model clear instructions.
        
        Args:
            render_state: The current render state with scene information.
            visual_style: The visual style description for the comic.
        
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

        # Join all parts into a coherent prompt
        full_prompt = ". ".join(prompt_parts)

        return full_prompt


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
    ) -> Optional[str]:
        """Generate a mock image without making API calls.
        
        Creates a text file documenting what would have been sent to the API,
        useful for testing and debugging without incurring API costs.
        
        Args:
            render_state: The current render state containing scene information.
            visual_style: The visual style description for the comic.
        
        Returns:
            The absolute path to the generated text file.
        """
        # Increment call counter for unique filenames
        self._call_count += 1
        
        # Build the prompt that would be sent to the API
        prompt = self._build_prompt(render_state, visual_style)

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

        return str(filepath)
