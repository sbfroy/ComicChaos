"""Static configuration for comic worlds.

The blueprint provides the foundation for a comic world, but the LLM
dynamically creates locations and characters as the story evolves.
Only the world description, starting location, and main character
are defined upfront - everything else emerges from the narrative.
"""

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class StartingLocation(BaseModel):
    """The initial location where the story begins."""

    name: str = Field(description="Location name")
    description: str = Field(description="Detailed description of the location")
    visual_description: str = Field(description="Visual description for image generation")


class MainCharacter(BaseModel):
    """The main protagonist of the comic."""

    name: str = Field(description="Character's name")
    description: str = Field(description="Visual and personality description")


class WorldBlueprint(BaseModel):
    """The comic world definition.

    This is intentionally minimal - it sets up the world's foundation,
    but the LLM brings it to life by dynamically creating locations
    and characters as the story evolves.
    """

    title: str = Field(description="Comic title")
    synopsis: str = Field(description="Brief story synopsis/hook")
    setting: str = Field(description="World description - the overall setting and atmosphere")
    starting_location: StartingLocation = Field(description="Where the story begins")
    main_character: MainCharacter = Field(description="The protagonist")
    goal: str = Field(description="Story concept/premise - what kind of story should unfold")
    visual_style: str = Field(
        default="comic book style, vibrant colors",
        description="Art style for generated images"
    )

    # World rules that the LLM should respect when creating new content
    world_rules: list[str] = Field(
        default_factory=list,
        description="Rules/constraints for the world that the LLM should follow"
    )


class StaticConfig(BaseModel):
    """Complete comic configuration.

    This holds only the initial blueprint - the foundation of the world.
    Dynamic content (new locations, characters) is stored in GameState.
    """

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
