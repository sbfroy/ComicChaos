"""Comic strip collector and generation functionality."""

from pathlib import Path
from datetime import datetime
from typing import Optional

from PIL import Image

from .config import COMIC_STRIPS_DIR


class ComicStrip:
    """Collects comic panels and generates the final strip."""

    def __init__(self, title: str = "My Comic"):
        self.output_dir = Path(COMIC_STRIPS_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.title = title
        self.panels: list[dict] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def add_panel(self, image_path: str | None, narrative: str, panel_number: int) -> None:
        """Add a panel to the comic strip."""
        self.panels.append({
            "image_path": image_path,
            "narrative": narrative,
            "panel_number": panel_number
        })

    def get_panel_count(self) -> int:
        """Get the number of panels in the comic."""
        return len(self.panels)

    def generate_comic_strip(self, max_panels_per_row: int = 3) -> Optional[str]:
        """Generate a single image showing all panels as a comic strip."""
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

        # Load and resize all images
        images = []
        for panel in valid_panels:
            try:
                img = Image.open(panel["image_path"])
                img = img.resize((panel_width, panel_height), Image.Resampling.LANCZOS)
                images.append(img)
            except Exception:
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

    def get_summary(self) -> str:
        """Get a text summary of the comic."""
        lines = [f"=== {self.title} ===", ""]
        for panel in self.panels:
            lines.append(f"Panel {panel['panel_number']}: {panel['narrative']}")
            if panel['image_path']:
                lines.append(f"  Image: {panel['image_path']}")
            lines.append("")
        return "\n".join(lines)
