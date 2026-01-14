"""Comic strip collector and display functionality."""

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

from PIL import Image

from .config import COMIC_STRIPS_DIR


class ComicStrip:
    """Collects comic panels and can display/export them."""

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

    def show_panel(self, image_path: str | None) -> None:
        """Display a single panel image immediately."""
        if not image_path or not Path(image_path).exists():
            return

        self._open_image(image_path)

    def _open_image(self, image_path: str) -> None:
        """Open an image with the system viewer."""
        abs_path = str(Path(image_path).resolve())

        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", abs_path],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                os.startfile(abs_path)
            else:
                # Linux - check if we're in WSL first
                is_wsl = False
                try:
                    with open("/proc/version", "r") as f:
                        is_wsl = "microsoft" in f.read().lower()
                except Exception:
                    try:
                        is_wsl = "microsoft" in os.uname().release.lower()
                    except Exception:
                        pass

                if is_wsl:
                    # WSL - try multiple methods to open the image
                    try:
                        # Convert to Windows path
                        result = subprocess.run(
                            ["wslpath", "-w", abs_path],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0:
                            win_path = result.stdout.strip()

                            # Method 1: Try wslview if available (from wslu package)
                            try:
                                subprocess.Popen(
                                    ["wslview", abs_path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL
                                )
                                return
                            except FileNotFoundError:
                                pass

                            # Method 2: Use powershell with Invoke-Item
                            try:
                                # Escape the path for PowerShell
                                escaped_path = win_path.replace("'", "''")
                                subprocess.Popen(
                                    ["powershell.exe", "-NoProfile", "-Command",
                                     f"Invoke-Item '{escaped_path}'"],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL
                                )
                                return
                            except Exception:
                                pass

                            # Method 3: Use cmd.exe with start
                            try:
                                subprocess.Popen(
                                    ["cmd.exe", "/c", f'start "" "{win_path}"'],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    shell=True
                                )
                                return
                            except Exception:
                                pass

                    except Exception:
                        pass

                # Native Linux - try common viewers
                for viewer in ["xdg-open", "eog", "feh", "display", "gpicview", "open"]:
                    try:
                        subprocess.Popen(
                            [viewer, abs_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        return
                    except FileNotFoundError:
                        continue

        except Exception as e:
            print(f"Could not open image: {e}")
            print(f"Image saved at: {abs_path}")

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
        gap = 2  # Small gap between panels

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

    def show_final_comic(self, cleanup_panels: bool = True) -> Optional[str]:
        """Generate and display the final comic strip.

        Args:
            cleanup_panels: If True, delete individual panel images after generating the strip.
        """
        strip_path = self.generate_comic_strip()
        if strip_path:
            print(f"\nComic strip saved to: {strip_path}")
            self._open_image(strip_path)

            if cleanup_panels:
                self._cleanup_panel_images()

        return strip_path

    def _cleanup_panel_images(self) -> None:
        """Delete individual panel images to save space."""
        for panel in self.panels:
            image_path = panel.get("image_path")
            if image_path:
                try:
                    path = Path(image_path)
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass  # Ignore cleanup errors

    def get_summary(self) -> str:
        """Get a text summary of the comic."""
        lines = [f"=== {self.title} ===", ""]
        for panel in self.panels:
            lines.append(f"Panel {panel['panel_number']}: {panel['narrative']}")
            if panel['image_path']:
                lines.append(f"  Image: {panel['image_path']}")
            lines.append("")
        return "\n".join(lines)
