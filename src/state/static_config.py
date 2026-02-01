"""Static configuration for comic worlds.

The blueprint provides the foundation for a comic world.
The first location is the starting location and the first character is the main character.
"""

import json
from pathlib import Path
from pydantic import BaseModel, Field


class Location(BaseModel):
    """A location in the comic world."""

    name: str = Field(description="Location name")
    description: str = Field(description="Brief description (1-2 sentences: setting type, key atmosphere)")


class Character(BaseModel):
    """A character in the comic world."""

    name: str = Field(description="Character's name")
    description: str = Field(description="Brief description (1-2 sentences: 2-3 key visual features + 1 personality trait)")


class Blueprint(BaseModel):
    """The comic setting definition.

    The first location is the starting location and the first character
    is the main character.
    """

    title: str = Field(description="Comic title")
    synopsis: str = Field(description="Brief story synopsis/hook")
    locations: list[Location] = Field(
        default_factory=list,
        description="Pre-defined locations (first one is the starting location)"
    )
    characters: list[Character] = Field(
        default_factory=list,
        description="Pre-defined characters (first one is the main character)"
    )
    visual_style: str = Field(
        default="comic book style, vibrant colors",
        description="Art style for generated images"
    )
    rules: list[str] = Field(
        default_factory=list,
        description="Rules/constraints for the world that the LLM should follow"
    )
    long_term_goals: list[str] = Field(
        default_factory=list,
        description="Blueprint-defined long-term story goals that anchor the narrative arc"
    )

    @property
    def starting_location(self) -> Location | None:
        """Get the starting location (first in the list)."""
        return self.locations[0] if self.locations else None

    @property
    def main_character(self) -> Character | None:
        """Get the main character (first in the list)."""
        return self.characters[0] if self.characters else None


class StaticConfig(BaseModel):
    """Complete comic configuration."""

    blueprint: Blueprint | None = None

    @classmethod
    def load_from_directory(cls, config_dir: str | Path) -> "StaticConfig":
        """Load configuration from a directory."""
        config_dir = Path(config_dir)

        blueprint = None

        blueprint_file = config_dir / "blueprint.json"
        if blueprint_file.exists():
            with open(blueprint_file) as f:
                data = json.load(f)
                blueprint = Blueprint(**data)

        return cls(blueprint=blueprint)
