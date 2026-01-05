"""Static configuration for comic worlds."""

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class Character(BaseModel):
    """A character in the comic world."""

    id: str = Field(description="Unique identifier")
    name: str = Field(description="Character's name")
    description: str = Field(description="Visual and personality description")
    location_id: str = Field(description="Starting location ID")
    role: str = Field(default="character", description="Role: player, character, supporting")


class Location(BaseModel):
    """A location in the comic world."""

    id: str = Field(description="Unique identifier")
    name: str = Field(description="Location name")
    description: str = Field(description="Detailed description")
    visual_description: str = Field(default="", description="Visual description for image generation")
    connections: dict[str, str] = Field(default_factory=dict, description="Direction -> location_id")
    accessible: bool = Field(default=True)


class WorldBlueprint(BaseModel):
    """The comic world definition."""

    title: str = Field(description="Comic title")
    synopsis: str = Field(description="Story synopsis")
    setting: str = Field(description="Setting description")
    starting_location_id: str = Field(description="Where the story starts")
    goal: str = Field(description="Story concept/premise")
    locations: list[Location] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    visual_style: str = Field(
        default="comic book style, vibrant colors",
        description="Art style for generated images"
    )


class StaticConfig(BaseModel):
    """Complete comic configuration."""

    world_blueprint: WorldBlueprint | None = None

    @classmethod
    def load_from_directory(cls, config_dir: str | Path) -> "StaticConfig":
        """Load configuration from a directory."""
        config_dir = Path(config_dir)

        world_blueprint = None

        blueprint_file = config_dir / "world_blueprint.json"
        if blueprint_file.exists():
            with open(blueprint_file) as f:
                data = json.load(f)
                world_blueprint = WorldBlueprint(**data)

        return cls(world_blueprint=world_blueprint)

    def get_location_by_id(self, location_id: str) -> Location | None:
        """Get a location by ID."""
        if not self.world_blueprint:
            return None
        for loc in self.world_blueprint.locations:
            if loc.id == location_id:
                return loc
        return None

    def get_character_by_id(self, character_id: str) -> Character | None:
        """Get a character by ID."""
        if not self.world_blueprint:
            return None
        for char in self.world_blueprint.characters:
            if char.id == character_id:
                return char
        return None
