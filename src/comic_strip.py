"""Comic strip collector and generation functionality."""

from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from PIL import Image

from .config import COMIC_STRIPS_DIR
from .image_gen.bubble_detector import BubbleDetector
from .image_gen.text_renderer import TextRenderer, TextElement


class ComicStrip:
    """Collects comic panels and generates the final strip."""


    def __init__(self, title: str = "My Comic"):
        self.output_dir = Path(COMIC_STRIPS_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.title = title
        self.panels: list[dict] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Initialize bubble detection and text rendering for final strip
        self.bubble_detector = BubbleDetector()
        self.text_renderer = TextRenderer()

    def add_panel(
        self,
        image_path: str | None,
        narrative: str,
        panel_number: int,
        elements: List[Dict[str, Any]] | None = None,
        user_input_text: str | None = None,
        detected_bubbles: List[Dict[str, Any]] | None = None,
    ) -> None:
        """Add a panel to the comic strip.

        Args:
            image_path: Path to the panel image.
            narrative: Text narrative for the panel.
            panel_number: The panel number.
            elements: Optional list of elements with text content.
            user_input_text: Optional user input text for this panel.
            detected_bubbles: Optional list of detected bubble positions.
        """
        self.panels.append({
            "image_path": image_path,
            "narrative": narrative,
            "panel_number": panel_number,
            "elements": elements or [],
            "user_input_text": user_input_text,
            "detected_bubbles": detected_bubbles or [],
        })

    def get_panel_count(self) -> int:
        """Get the number of panels in the comic."""
        return len(self.panels)

    def generate_comic_strip(self, max_panels_per_row: int = 3) -> Optional[str]:
        """Generate a single image showing all panels as a comic strip.

        This method processes each panel to detect bubbles and render text
        into them before compositing the final strip.
        """
        if not self.panels:
            return None

        # Filter panels that have valid images
        valid_panels = [p for p in self.panels if p["image_path"] and Path(p["image_path"]).exists()]

        if not valid_panels:
            return None

        # Panel dimensions for the comic strip
        panel_width = 512
        panel_height = 512
        border = 4
        gap = 2

        # Process and load all images
        images = []
        for panel in valid_panels:
            try:
                # Process bubbles for this panel
                processed_img = self._process_panel_bubbles(panel)
                if processed_img:
                    processed_img = processed_img.resize(
                        (panel_width, panel_height), Image.Resampling.LANCZOS
                    )
                    images.append(processed_img)
                else:
                    # Fall back to raw image
                    img = Image.open(panel["image_path"])
                    img = img.resize((panel_width, panel_height), Image.Resampling.LANCZOS)
                    images.append(img)
            except Exception as e:
                print(f"Error processing panel: {e}")
                continue

        if not images:
            return None

        # Calculate layout
        num_panels = len(images)
        cols = min(num_panels, max_panels_per_row)
        rows = (num_panels + cols - 1) // cols

        # Calculate total dimensions
        total_width = cols * panel_width + (cols - 1) * gap + border * 2
        total_height = rows * panel_height + (rows - 1) * gap + border * 2

        # Create the comic strip image
        strip = Image.new("RGB", (total_width, total_height), "black")

        # Place panels
        for i, img in enumerate(images):
            row = i // cols
            col = i % cols

            x = border + col * (panel_width + gap)
            y = border + row * (panel_height + gap)

            strip.paste(img, (x, y))

        # Save the comic strip
        output_path = self.output_dir / f"comic_strip_{self.session_id}.png"
        strip.save(output_path)

        return str(output_path)

    def _process_panel_bubbles(self, panel: dict) -> Optional[Image.Image]:
        """Process a panel to render text into detected bubbles.

        Speech/thought bubbles are rendered into detected bubble regions.
        Narration boxes are drawn in corners (not part of the generated image).

        Args:
            panel: Panel dictionary with image_path, elements, user_input_text, detected_bubbles.

        Returns:
            Processed PIL Image with text rendered, or None on failure.
        """
        image_path = panel.get("image_path")
        elements = panel.get("elements", [])
        user_input_text = panel.get("user_input_text")
        stored_bubbles = panel.get("detected_bubbles", [])

        if not image_path or not Path(image_path).exists():
            return None

        try:
            # Load the image
            img = Image.open(image_path)
            img_width, img_height = img.size

            # Convert stored bubble dicts to DetectedBubble objects
            from .image_gen.bubble_detector import DetectedBubble
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
                detected_bubbles = self.bubble_detector.detect_bubbles(image_path)

            # Separate elements by type
            speech_thought_elements = []
            narration_elements = []

            for el in elements:
                el_type = el.get("type", "")
                if el_type in ("speech", "thought"):
                    speech_thought_elements.append(el)
                elif el_type == "narration":
                    narration_elements.append(el)
                # SFX are skipped for final strip (they're visual in the image)

            # Step 1: Render text into detected bubbles for speech/thought
            bubble_idx = 0
            for el in speech_thought_elements:
                if bubble_idx >= len(detected_bubbles):
                    break

                bubble = detected_bubbles[bubble_idx]
                bubble_idx += 1

                # Determine text
                if el.get("user_input"):
                    text = user_input_text or ""
                else:
                    text = el.get("text", "")

                if not text:
                    continue

                text_element = TextElement(
                    text=text,
                    element_type=el.get("type", "speech"),
                    character_name=el.get("character_name"),
                    position=el.get("position"),
                )
                img = self.text_renderer.render_text_on_image(img, bubble, text_element)

            # Step 2: Draw narration boxes in corners
            corner_positions = ["top-left", "top-right", "bottom-left", "bottom-right"]
            for i, el in enumerate(narration_elements):
                text = el.get("text", "")
                if el.get("user_input"):
                    text = user_input_text or ""

                if not text:
                    continue

                # Use element's position or assign a corner
                position = el.get("position", corner_positions[i % len(corner_positions)])

                text_element = TextElement(
                    text=text,
                    element_type="narration",
                    character_name=None,
                    position=position,
                )
                img = self.text_renderer.draw_programmatic_bubble(
                    img, text_element, img_width, img_height
                )

            return img

        except Exception as e:
            print(f"Error processing panel bubbles: {e}")
            return None

    def get_summary(self) -> str:
        """Get a text summary of the comic."""
        lines = [f"=== {self.title} ===", ""]
        for panel in self.panels:
            lines.append(f"Panel {panel['panel_number']}: {panel['narrative']}")
            if panel['image_path']:
                lines.append(f"  Image: {panel['image_path']}")
            lines.append("")
        return "\n".join(lines)
