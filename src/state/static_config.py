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
    long_term_narrative: list[str] = Field(
        default_factory=list,
        description="Blueprint-defined long-term narrative directions that anchor the story arc"
    )
    narrative_premise: str = Field(
        default="",
        description="The thematic engine of the comic — what the story is fundamentally about. Guides tone and conflict without implying an ending."
    )

    @property
    def starting_location(self) -> Location | None:
        """Get the starting location (first in the list)."""
        return self.locations[0] if self.locations else None

    @property
    def main_character(self) -> Character | None:
        """Get the main character (first in the list)."""
        return self.characters[0] if self.characters else None


class ComicConfig(BaseModel):
    """Per-comic technical configuration for models, fonts, and generation settings."""

    panel_font: str = Field(
        default="'Comic Sans MS', 'Chalkboard', cursive, sans-serif",
        description="CSS font-family string for in-panel text"
    )
    llm_model: str = Field(default="gpt-4o-mini")
    llm_temperature: float = Field(default=0.8)
    llm_top_p: float = Field(default=0.9)
    llm_max_tokens: int = Field(default=1500)
    image_model: str = Field(default="gpt-image-1-mini")
    image_size: str = Field(default="1024x1024")
    image_quality: str = Field(default="low")
    image_moderation: str = Field(default="low")


class StaticConfig(BaseModel):
    """Complete comic configuration."""

    blueprint: Blueprint | None = None
    comic_config: ComicConfig = Field(default_factory=ComicConfig)

    @classmethod
    def load_from_directory(cls, config_dir: str | Path, language: str = "en") -> "StaticConfig":
        """Load configuration from a directory.

        If *language* is not ``"en"`` and a ``blueprint.{language}.json``
        file exists in the directory it will be loaded instead of the
        default ``blueprint.json``.
        """
        config_dir = Path(config_dir)

        blueprint = None
        comic_config = ComicConfig()

        # Try language-specific blueprint first, fall back to default
        blueprint_file = config_dir / f"blueprint.{language}.json"
        if language == "en" or not blueprint_file.exists():
            blueprint_file = config_dir / "blueprint.json"
        if blueprint_file.exists():
            with open(blueprint_file) as f:
                data = json.load(f)
                blueprint = Blueprint(**data)

        config_file = config_dir / "config.json"
        if config_file.exists():
            with open(config_file) as f:
                data = json.load(f)
                comic_config = ComicConfig(**data)

        return cls(blueprint=blueprint, comic_config=comic_config)
