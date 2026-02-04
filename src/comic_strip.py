"""Comic strip collector and generation functionality."""

from io import BytesIO
from typing import Optional, List, Dict, Any

from PIL import Image, ImageDraw

from .image_gen.panel_detector import PanelDetector, DetectedRegion as DetectedBubble
from .image_gen.text_renderer import TextRenderer, TextElement


class ComicStrip:
    """Collects comic panels and generates the final strip."""


    def __init__(self, title: str = "My Comic"):
        self.title = title
        self.panels: list[dict] = []

        # Initialize panel detection and text rendering for final strip
        self.panel_detector = PanelDetector()
        self.text_renderer = TextRenderer()

    def add_panel(
        self,
        image_bytes: bytes | None,
        narrative: str,
        panel_number: int,
        elements: List[Dict[str, Any]] | None = None,
        user_input_text: str | None = None,
        detected_bubbles: List[Dict[str, Any]] | None = None,
    ) -> None:
        """Add a panel to the comic strip.

        Args:
            image_bytes: Raw PNG image bytes for the panel.
            narrative: Text narrative for the panel.
            panel_number: The panel number.
            elements: Optional list of elements with text content.
            user_input_text: Optional user input text for this panel.
            detected_bubbles: Optional list of detected bubble positions.
        """
        self.panels.append({
            "image_bytes": image_bytes,
            "narrative": narrative,
            "panel_number": panel_number,
            "elements": elements or [],
            "user_input_text": user_input_text,
            "detected_bubbles": detected_bubbles or [],
        })

    def get_panel_count(self) -> int:
        """Get the number of panels in the comic."""
        return len(self.panels)

    def generate_comic_strip(self, max_panels_per_row: int = 3) -> Optional[bytes]:
        """Generate a single image showing all panels as a comic strip.

        This method processes each panel to detect bubbles and render text
        into them before compositing the final strip.

        Returns:
            PNG image as bytes, or None on failure.
        """
        if not self.panels:
            return None

        # Filter panels that have valid images
        valid_panels = [p for p in self.panels if p["image_bytes"]]

        if not valid_panels:
            return None

        # Layout constants matching the CSS workspace styling
        panel_size = 512
        gap = 12                # matches CSS grid gap: 12px
        page_padding = 12      # matches CSS .comic-page padding: 12px
        panel_border = 4       # matches CSS --border-thick: 4px
        outer_border = 4       # matches CSS .pages-wrapper border
        page_margin = 20       # margin around the page wrapper

        # Colors matching CSS variables
        color_paper = (245, 240, 230)       # --color-paper: #f5f0e6
        color_border = (17, 17, 17)         # --color-black: #111
        color_bg = (23, 101, 185)           # --color-primary-blue: #1765B9

        # Process and load all images
        images = []
        for panel in valid_panels:
            try:
                processed_img = self._process_panel_bubbles(panel)
                if processed_img:
                    processed_img = processed_img.resize(
                        (panel_size, panel_size), Image.Resampling.LANCZOS
                    )
                    images.append(processed_img)
                else:
                    img = Image.open(BytesIO(panel["image_bytes"]))
                    img = img.resize((panel_size, panel_size), Image.Resampling.LANCZOS)
                    images.append(img)
            except Exception as e:
                print(f"Error processing panel: {e}")
                continue

        if not images:
            return None

        # Calculate grid layout
        num_panels = len(images)
        cols = min(num_panels, max_panels_per_row)
        rows = (num_panels + cols - 1) // cols

        # Each panel cell includes its border
        cell_size = panel_size + panel_border * 2

        # Page interior dimensions (the paper area inside the outer border)
        page_inner_w = page_padding * 2 + cols * cell_size + (cols - 1) * gap
        page_inner_h = page_padding * 2 + rows * cell_size + (rows - 1) * gap

        # Total canvas includes margin + outer border + page interior
        total_width = page_margin * 2 + outer_border * 2 + page_inner_w
        total_height = page_margin * 2 + outer_border * 2 + page_inner_h

        # Create canvas with blue background
        strip = Image.new("RGB", (total_width, total_height), color_bg)
        draw = ImageDraw.Draw(strip)

        # Draw the outer border rectangle (pages-wrapper)
        outer_x = page_margin
        outer_y = page_margin
        outer_w = outer_border * 2 + page_inner_w
        outer_h = outer_border * 2 + page_inner_h
        draw.rectangle(
            [outer_x, outer_y, outer_x + outer_w - 1, outer_y + outer_h - 1],
            fill=color_paper,
            outline=color_border,
            width=outer_border,
        )

        # Origin for panel placement (inside outer border + page padding)
        origin_x = page_margin + outer_border + page_padding
        origin_y = page_margin + outer_border + page_padding

        # Place panels with individual borders
        for i, img in enumerate(images):
            row = i // cols
            col = i % cols

            cell_x = origin_x + col * (cell_size + gap)
            cell_y = origin_y + row * (cell_size + gap)

            # Draw panel border
            draw.rectangle(
                [cell_x, cell_y, cell_x + cell_size - 1, cell_y + cell_size - 1],
                outline=color_border,
                width=panel_border,
            )

            # Paste image inside the border
            img_x = cell_x + panel_border
            img_y = cell_y + panel_border
            strip.paste(img, (img_x, img_y))

        # Return as PNG bytes
        buf = BytesIO()
        strip.save(buf, format="PNG")
        return buf.getvalue()

    def _process_panel_bubbles(self, panel: dict) -> Optional[Image.Image]:
        """Process a panel to render text into detected bubbles.

        Speech/thought bubbles are rendered into detected bubble regions.
        Narration boxes are drawn in corners (not part of the generated image).

        Args:
            panel: Panel dictionary with image_bytes, elements, user_input_text, detected_bubbles.

        Returns:
            Processed PIL Image with text rendered, or None on failure.
        """
        image_bytes = panel.get("image_bytes")
        elements = panel.get("elements", [])
        user_input_text = panel.get("user_input_text")
        stored_bubbles = panel.get("detected_bubbles", [])

        if not image_bytes:
            return None

        try:
            # Load the image from bytes
            img = Image.open(BytesIO(image_bytes))
            img_width, img_height = img.size

            # Convert stored bubble dicts to DetectedBubble objects
            detected_bubbles = []
            for b in stored_bubbles:
                detected_bubbles.append(DetectedBubble(
                    x=b["x"],
                    y=b["y"],
                    width=b["width"],
                    height=b["height"],
                    contour=None,
                ))

            # If no stored bubbles, try to detect them
            if not detected_bubbles:
                detected_bubbles = self.panel_detector.detect_bubbles(image_bytes)

            # Render text into detected bubbles for all element types
            # Falls back to programmatic overlay when no detected bubble available
            bubble_idx = 0
            for el in elements:
                el_type = el.get("type", "")
                if el_type not in ("speech", "thought", "narration"):
                    continue

                # Determine text
                if el.get("user_input"):
                    text = user_input_text or ""
                else:
                    text = el.get("text", "")

                if not text:
                    continue

                text_element = TextElement(
                    text=text,
                    element_type=el_type,
                    position=el.get("position"),
                )

                if bubble_idx < len(detected_bubbles):
                    # Render into detected region
                    img = self.text_renderer.render_text_on_image(
                        img, detected_bubbles[bubble_idx], text_element
                    )
                    bubble_idx += 1
                else:
                    # Fallback: programmatic overlay
                    img = self.text_renderer.draw_programmatic_bubble(
                        img, text_element, img_width, img_height
                    )

            return img

        except Exception as e:
            print(f"Error processing panel bubbles: {e}")
            return None
