"""Text rendering module for comic bubbles.

This module renders text into detected bubble regions,
handling text wrapping, sizing, and positioning. Also supports
drawing programmatic bubbles for elements without detected regions.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .bubble_detector import DetectedBubble


@dataclass
class TextElement:
    """Represents text to be rendered into a bubble."""

    text: str
    element_type: str  # "speech", "thought", "narration", "sfx"
    character_name: Optional[str] = None
    position: Optional[str] = None  # Position hint for programmatic bubbles


class TextRenderer:
    """Renders text into comic bubble regions."""

    def __init__(
        self,
        font_path: Optional[str] = None,
        default_font_size: int = 20,
        min_font_size: int = 12,
        padding_ratio: float = 0.15,
        line_spacing: float = 1.2,
    ):
        """Initialize the text renderer.

        Args:
            font_path: Path to a TrueType font file. Uses default if None.
            default_font_size: Starting font size to try.
            min_font_size: Minimum font size before giving up.
            padding_ratio: Ratio of bubble size to use as padding.
            line_spacing: Line spacing multiplier.
        """
        self.font_path = font_path
        self.default_font_size = default_font_size
        self.min_font_size = min_font_size
        self.padding_ratio = padding_ratio
        self.line_spacing = line_spacing

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """Get a font at the specified size.

        Args:
            size: Font size in pixels.
            bold: Whether to use bold variant.

        Returns:
            PIL ImageFont object.
        """
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except (OSError, IOError):
                pass

        # Try common comic-style fonts
        comic_fonts = [
            "Comic Sans MS",
            "ComicSansMS",
            "comic.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/comic.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

        for font_name in comic_fonts:
            try:
                return ImageFont.truetype(font_name, size)
            except (OSError, IOError):
                continue

        # Fall back to default font
        return ImageFont.load_default()

    def _wrap_text(
        self, text: str, font: ImageFont.FreeTypeFont, max_width: int
    ) -> List[str]:
        """Wrap text to fit within a maximum width.

        Args:
            text: Text to wrap.
            font: Font to use for measurement.
            max_width: Maximum width in pixels.

        Returns:
            List of wrapped lines.
        """
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = font.getbbox(test_line)
            width = bbox[2] - bbox[0]

            if width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

        return lines if lines else [text]

    def _truncate_text_to_fit(
        self, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_height: int
    ) -> List[str]:
        """Truncate text from the end to fit within dimensions.

        This keeps the oldest (beginning) text and truncates the newest (ending) text.

        Args:
            text: Text to truncate.
            font: Font to use for measurement.
            max_width: Maximum width in pixels.
            max_height: Maximum height in pixels.

        Returns:
            List of wrapped lines that fit, with ellipsis if truncated.
        """
        words = text.split()

        # Try progressively fewer words until it fits
        for word_count in range(len(words), 0, -1):
            truncated_text = " ".join(words[:word_count])
            if word_count < len(words):
                truncated_text += "..."

            lines = self._wrap_text(truncated_text, font, max_width)
            _, text_height = self._calculate_text_bounds(lines, font)

            if text_height <= max_height:
                return lines

        # If even one word doesn't fit, return it anyway
        return [words[0] + "..." if len(words) > 1 else words[0]] if words else ["..."]

    def _calculate_text_bounds(
        self,
        lines: List[str],
        font: ImageFont.FreeTypeFont,
    ) -> Tuple[int, int]:
        """Calculate the total bounds of wrapped text.

        Args:
            lines: List of text lines.
            font: Font to use for measurement.

        Returns:
            Tuple of (width, height).
        """
        max_width = 0
        total_height = 0

        for i, line in enumerate(lines):
            bbox = font.getbbox(line)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]

            max_width = max(max_width, line_width)
            total_height += int(line_height * self.line_spacing)

        return max_width, total_height

    def _find_best_font_size(
        self,
        text: str,
        bubble: DetectedBubble,
        character_name: Optional[str] = None,
    ) -> Tuple[ImageFont.FreeTypeFont, List[str], int]:
        """Find the best font size that fits text in the bubble.

        Args:
            text: Text to render.
            bubble: Bubble to fit text into.
            character_name: Optional character name to include.

        Returns:
            Tuple of (font, wrapped_lines, name_height).
        """
        # Calculate usable area with padding
        padding_x = int(bubble.width * self.padding_ratio)
        padding_y = int(bubble.height * self.padding_ratio)
        usable_width = bubble.width - (2 * padding_x)
        usable_height = bubble.height - (2 * padding_y)

        # Scale starting font size based on text length, matching frontend
        # Images are 1024x1024, bubbles are typically 150-250px in that space
        # In the 512x512 final strip, that's 75-125px
        # We want fonts around 13px for short text, scaling down

        text_length = len(text)

        # Use text length as primary factor (matching frontend exactly)
        if text_length < 15:
            target_size = 26  # Will scale down to ~13px at 512x512
        elif text_length < 30:
            target_size = 24  # ~12px
        elif text_length < 50:
            target_size = 22  # ~11px
        elif text_length < 70:
            target_size = 20  # ~10px
        else:
            target_size = 18  # ~9px

        # Cap based on bubble size to avoid overflow
        bubble_min_dim = min(bubble.width, bubble.height)
        max_size = int(bubble_min_dim * 0.15)

        scaled_start_size = max(self.min_font_size, min(target_size, max_size))

        # Account for character name if present
        name_height = 0

        for font_size in range(scaled_start_size, self.min_font_size - 1, -1):
            font = self._get_font(font_size)
            name_font = self._get_font(max(font_size - 4, 10), bold=True)

            # Calculate name height
            if character_name:
                name_bbox = name_font.getbbox(character_name.upper())
                name_height = int((name_bbox[3] - name_bbox[1]) * 1.5)

            available_height = usable_height - name_height

            # Wrap text
            lines = self._wrap_text(text, font, usable_width)

            # Check if it fits
            text_width, text_height = self._calculate_text_bounds(lines, font)

            if text_width <= usable_width and text_height <= available_height:
                return font, lines, name_height

        # If text doesn't fit even at minimum size, truncate from end
        font = self._get_font(self.min_font_size)
        name_font = self._get_font(max(self.min_font_size - 4, 10), bold=True)

        if character_name:
            name_bbox = name_font.getbbox(character_name.upper())
            name_height = int((name_bbox[3] - name_bbox[1]) * 1.5)

        available_height = usable_height - name_height
        lines = self._truncate_text_to_fit(text, font, usable_width, available_height)
        return font, lines, name_height

    def render_text_on_image(
        self,
        image: Image.Image,
        bubble: DetectedBubble,
        element: TextElement,
    ) -> Image.Image:
        """Render text onto an image within a bubble region.

        Args:
            image: PIL Image to render onto.
            bubble: Detected bubble region.
            element: Text element to render.

        Returns:
            Modified PIL Image.
        """
        if not element.text.strip():
            return image

        # Make a copy to avoid modifying original
        img = image.copy()
        draw = ImageDraw.Draw(img)

        # Find best font size and wrap text
        font, lines, name_height = self._find_best_font_size(
            element.text,
            bubble,
            element.character_name if element.element_type in ("speech", "thought") else None,
        )

        # Calculate padding
        padding_x = int(bubble.width * self.padding_ratio)
        padding_y = int(bubble.height * self.padding_ratio)

        # Calculate text positioning
        _, text_height = self._calculate_text_bounds(lines, font)

        # Start position (centered in bubble)
        total_content_height = name_height + text_height
        start_y = bubble.y + padding_y + (bubble.height - 2 * padding_y - total_content_height) // 2

        # Set colors based on element type
        if element.element_type == "sfx":
            text_color = (220, 38, 38)  # Red for SFX
            outline_color = (251, 191, 36)  # Yellow outline
        elif element.element_type == "narration":
            text_color = (17, 17, 17)  # Dark for narration
            outline_color = None
        else:
            text_color = (17, 17, 17)  # Dark for speech/thought
            outline_color = None

        # Draw character name if applicable
        current_y = start_y
        if element.character_name and element.element_type in ("speech", "thought"):
            name_font = self._get_font(max(font.size - 4 if hasattr(font, 'size') else 14, 10))
            name_text = element.character_name.upper()
            name_bbox = name_font.getbbox(name_text)
            name_width = name_bbox[2] - name_bbox[0]
            name_x = bubble.x + (bubble.width - name_width) // 2

            # Name color based on type
            name_color = (220, 38, 38) if element.element_type == "speech" else (6, 182, 212)
            draw.text((name_x, current_y), name_text, font=name_font, fill=name_color)
            current_y += name_height

        # Draw each line of text
        for line in lines:
            line_bbox = font.getbbox(line)
            line_width = line_bbox[2] - line_bbox[0]
            line_height = line_bbox[3] - line_bbox[1]

            # Center horizontally
            x = bubble.x + (bubble.width - line_width) // 2

            # Draw outline for SFX
            if outline_color:
                for dx in [-2, -1, 0, 1, 2]:
                    for dy in [-2, -1, 0, 1, 2]:
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, current_y + dy), line, font=font, fill=outline_color)

            # Draw main text
            draw.text((x, current_y), line, font=font, fill=text_color)

            current_y += int(line_height * self.line_spacing)

        return img

    def render_all_bubbles(
        self,
        image: Image.Image,
        bubbles: List[DetectedBubble],
        elements: List[TextElement],
    ) -> Image.Image:
        """Render text into all detected bubbles.

        Matches bubbles to elements based on position order.

        Args:
            image: PIL Image to render onto.
            bubbles: List of detected bubbles.
            elements: List of text elements to render.

        Returns:
            Modified PIL Image with all text rendered.
        """
        img = image.copy()

        # Match bubbles to elements (assuming same order)
        for i, (bubble, element) in enumerate(zip(bubbles, elements)):
            img = self.render_text_on_image(img, bubble, element)

        return img

    def draw_programmatic_bubble(
        self,
        image: Image.Image,
        element: TextElement,
        image_width: int,
        image_height: int,
    ) -> Image.Image:
        """Draw a programmatic bubble and render text into it.

        Used for pre-filled elements that don't have bubbles in the generated image.

        Args:
            image: PIL Image to draw onto.
            element: Text element with position and text.
            image_width: Width of the image.
            image_height: Height of the image.

        Returns:
            Modified PIL Image with bubble and text.
        """
        if not element.text.strip():
            return image

        img = image.copy()
        draw = ImageDraw.Draw(img)

        # Calculate bubble position and size based on position hint
        bubble_width = min(180, image_width // 3)
        bubble_height = min(100, image_height // 5)

        # Position mapping
        position = element.position or "center"
        margin = 15

        if "left" in position:
            x = margin
        elif "right" in position:
            x = image_width - bubble_width - margin
        else:
            x = (image_width - bubble_width) // 2

        if "top" in position:
            y = margin
        elif "bottom" in position:
            y = image_height - bubble_height - margin - 20  # Extra space for tail
        else:
            y = (image_height - bubble_height) // 2

        # Draw bubble based on type
        if element.element_type == "speech":
            self._draw_speech_bubble(draw, x, y, bubble_width, bubble_height)
        elif element.element_type == "thought":
            self._draw_thought_bubble(draw, x, y, bubble_width, bubble_height)
        elif element.element_type == "narration":
            self._draw_narration_box(draw, x, y, bubble_width, bubble_height)
        elif element.element_type == "sfx":
            # SFX doesn't need a bubble, just render text
            self._draw_sfx_text(draw, element, x, y, bubble_width, bubble_height)
            return img

        # Create a fake DetectedBubble for text rendering
        fake_bubble = DetectedBubble(
            x=x,
            y=y,
            width=bubble_width,
            height=bubble_height,
            contour=None,
        )

        # Render text into the bubble
        img = self.render_text_on_image(img, fake_bubble, element)

        return img

    def _draw_speech_bubble(
        self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int
    ) -> None:
        """Draw a speech bubble with tail."""
        # Main bubble (rounded rectangle approximation using ellipse)
        draw.rounded_rectangle(
            [x, y, x + width, y + height],
            radius=15,
            fill="white",
            outline="black",
            width=3,
        )

        # Draw tail (triangle pointing down-left)
        tail_x = x + 25
        tail_y = y + height
        draw.polygon(
            [
                (tail_x, tail_y - 5),
                (tail_x + 15, tail_y - 5),
                (tail_x - 5, tail_y + 15),
            ],
            fill="white",
            outline="black",
            width=2,
        )
        # Cover the outline inside the bubble
        draw.line([(tail_x + 1, tail_y - 3), (tail_x + 13, tail_y - 3)], fill="white", width=4)

    def _draw_thought_bubble(
        self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int
    ) -> None:
        """Draw a thought bubble with circular tail."""
        # Main bubble (rounded rectangle)
        draw.rounded_rectangle(
            [x, y, x + width, y + height],
            radius=20,
            fill="white",
            outline="black",
            width=3,
        )

        # Draw thought dots
        dot_x = x + 20
        dot_y = y + height + 5
        draw.ellipse([dot_x, dot_y, dot_x + 12, dot_y + 12], fill="white", outline="black", width=2)
        draw.ellipse([dot_x - 8, dot_y + 12, dot_x, dot_y + 20], fill="white", outline="black", width=2)

    def _draw_narration_box(
        self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int
    ) -> None:
        """Draw a narration box."""
        # Yellow/cream background rectangle
        draw.rectangle(
            [x, y, x + width, y + height],
            fill=(254, 243, 199),  # Light yellow
            outline="black",
            width=3,
        )

    def _draw_sfx_text(
        self,
        draw: ImageDraw.Draw,
        element: TextElement,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        """Draw sound effect text without a bubble."""
        font = self._get_font(28)
        text = element.text.upper()

        # Get text bounds
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]

        # Center in the area
        text_x = x + (width - text_width) // 2
        text_y = y + height // 3

        # Draw with shadow/outline effect
        shadow_color = (251, 191, 36)  # Yellow
        text_color = (220, 38, 38)  # Red

        for dx in [-3, -2, -1, 0, 1, 2, 3]:
            for dy in [-3, -2, -1, 0, 1, 2, 3]:
                if abs(dx) + abs(dy) > 0:
                    draw.text((text_x + dx, text_y + dy), text, font=font, fill=shadow_color)

        draw.text((text_x, text_y), text, font=font, fill=text_color)
