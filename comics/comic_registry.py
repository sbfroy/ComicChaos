"""Comic registry for managing multiple comics."""

import json
from pathlib import Path
from pydantic import BaseModel, Field

ARCHIVE_DIR_NAME = "archive"


class ComicInfo(BaseModel):
    """Metadata about a registered comic."""

    id: str = Field(description="Unique comic identifier (directory name)")
    name: str = Field(description="Display name")
    name_no: str = Field(default="", description="Display name in Norwegian")
    description: str = Field(description="Brief description")
    description_no: str = Field(default="", description="Brief description in Norwegian")
    style: str = Field(description="Visual style description")
    panel_font: str = Field(
        default="'Comic Sans MS', 'Chalkboard', cursive, sans-serif",
        description="CSS font-family for in-panel text"
    )


class ComicRegistry:
    """Registry for discovering and managing multiple comics."""

    def __init__(self, comics_dir: str | Path = "comics"):
        self.comics_dir = Path(comics_dir)
        self._comics: dict[str, ComicInfo] = {}
        self._discover_comics()

    def _discover_comics(self) -> None:
        """Discover all available comics."""
        if not self.comics_dir.exists():
            return

        for comic_path in self.comics_dir.iterdir():
            if comic_path.is_dir() and comic_path.name != ARCHIVE_DIR_NAME:
                blueprint_file = comic_path / "blueprint.json"
                if blueprint_file.exists():
                    # Load info from blueprint
                    with open(blueprint_file) as f:
                        bp_data = json.load(f)

                    # Load Norwegian blueprint for translated name/description
                    name_no = ""
                    description_no = ""
                    bp_no_file = comic_path / "blueprint.no.json"
                    if bp_no_file.exists():
                        with open(bp_no_file) as f:
                            bp_no_data = json.load(f)
                        name_no = bp_no_data.get("title", "")
                        description_no = bp_no_data.get("synopsis", "")

                    # Load panel font from config.json if present
                    panel_font = "'Comic Sans MS', 'Chalkboard', cursive, sans-serif"
                    config_file = comic_path / "config.json"
                    if config_file.exists():
                        with open(config_file) as f:
                            cfg_data = json.load(f)
                        panel_font = cfg_data.get("panel_font", panel_font)

                    self._comics[comic_path.name] = ComicInfo(
                        id=comic_path.name,
                        name=bp_data.get("title", comic_path.name),
                        name_no=name_no,
                        description=bp_data.get("synopsis", "No description"),
                        description_no=description_no,
                        style=bp_data.get("visual_style", "comic book style"),
                        panel_font=panel_font,
                    )

    def get_available_comics(self) -> list[ComicInfo]:
        """Get list of all available comics."""
        return list(self._comics.values())

    def get_comic_config_dir(self, comic_id: str) -> Path | None:
        """Get the config directory for a comic."""
        comic_dir = self.comics_dir / comic_id
        if comic_dir.exists():
            return comic_dir
        return None
