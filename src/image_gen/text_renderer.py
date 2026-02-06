"""Text rendering module for comic bubbles.

This module renders text into detected bubble regions,
handling text wrapping, sizing, and positioning. Also supports
drawing programmatic bubbles for elements without detected regions.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .panel_detector import DetectedRegion as DetectedBubble


@dataclass
class TextElement:
    """Represents text to be rendered into a bubble."""

    text: str
    element_type: str  # "speech", "thought", "narration", "sfx"
    character_name: Optional[str] = None
    position: Optional[str] = None  # Position hint for programmatic bubbles


class TextRenderer:
    """Renders text into comic bubble regions."""

    # Font sizes at 1024x1024 render resolution
    FONT_SIZES = [
        (15, 46),   # < 15 chars
        (30, 40),   # < 30 chars
        (50, 36),   # < 50 chars
        (None, 32), # >= 50 chars
    ]

    def __init__(
        self,
        font_path: Optional[str] = None,
        min_font_size: int = 12,
        padding_ratio: float = 0.15,
        line_spacing: float = 1.2,
    ):
        """Initialize the text renderer.

        Args:
            font_path: Path to a TrueType font file. Uses default if None.
            min_font_size: Minimum font size before giving up.
            padding_ratio: Ratio of bubble size to use as padding.
            line_spacing: Line spacing multiplier.
        """
        self.font_path = font_path
        self.min_font_size = min_font_size
        self.padding_ratio = padding_ratio
        self.line_spacing = line_spacing

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """Get a font at the specified size.

        Args:
            size: Font size in pixels.

        Returns:
            PIL ImageFont object.
        """
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except (OSError, IOError):
                pass

        # Try bundled Comic Neue first, then common comic-style fonts
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        comic_fonts = [
            os.path.join(base_dir, "static", "fonts", "ComicNeue-Regular.ttf"),
            "Comic Sans MS",
            "ComicSansMS",
            "comic.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/comic.ttf",
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

    def _get_target_font_size(self, text: str) -> int:
        """Get the target font size based on text length, matching frontend sizing.

        Args:
            text: The text to size.

        Returns:
            Font size in pixels (at 1024x1024 scale).
        """
        text_length = len(text)
        for threshold, size in self.FONT_SIZES:
            if threshold is None or text_length < threshold:
                return size
        return self.FONT_SIZES[-1][1]

    def _find_best_font_size(
        self,
        text: str,
        bubble: DetectedBubble,
    ) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
        """Find the best font size that fits text in the bubble.

        Args:
            text: Text to render.
            bubble: Bubble to fit text into.

        Returns:
            Tuple of (font, wrapped_lines).
        """
        # Calculate usable area with padding
        # CSS padding: 15% is relative to width for all sides, so match that
        padding = int(bubble.width * self.padding_ratio)
        usable_width = bubble.width - (2 * padding)
        usable_height = bubble.height - (2 * padding)

        target_size = self._get_target_font_size(text)

        for font_size in range(target_size, self.min_font_size - 1, -1):
            font = self._get_font(font_size)

            # Wrap text
            lines = self._wrap_text(text, font, usable_width)

            # Check if it fits
            text_width, text_height = self._calculate_text_bounds(lines, font)

            if text_width <= usable_width and text_height <= usable_height:
                return font, lines

        # If text doesn't fit even at minimum size, truncate from end
        font = self._get_font(self.min_font_size)
        lines = self._truncate_text_to_fit(text, font, usable_width, usable_height)
        return font, lines

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
        font, lines = self._find_best_font_size(element.text, bubble)

        # Calculate padding (CSS padding: 15% is relative to width for all sides)
        padding = int(bubble.width * self.padding_ratio)

        # Calculate text positioning (centered in bubble)
        _, text_height = self._calculate_text_bounds(lines, font)
        start_y = bubble.y + padding + (bubble.height - 2 * padding - text_height) // 2

        # Set colors based on element type
        if element.element_type == "sfx":
            text_color = (220, 38, 38)  # Red for SFX
            outline_color = (251, 191, 36)  # Yellow outline
        else:
            text_color = (17, 17, 17)  # Dark for speech/thought/narration
            outline_color = None

        # Draw each line of text
        current_y = start_y
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
