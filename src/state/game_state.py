"""Dynamic state for comic creation sessions."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from .static_config import StaticConfig


class ComicPanel(BaseModel):
    """A single panel in the comic strip."""

    panel_number: int = Field(description="Panel number in sequence")
    narrative: str = Field(description="The narrative text for this panel")
    image_path: str | None = Field(default=None, description="Path to generated image")
    player_action: str = Field(default="", description="What the player did")
    timestamp: datetime = Field(default_factory=datetime.now)


class NarrativeState(BaseModel):
    """Record of the comic story."""

    panels: list[ComicPanel] = Field(default_factory=list)
    rolling_summary: str = Field(
        default="The story has just begun.",
        description="Condensed summary of the story so far"
    )
    current_scene: str = Field(
        default="",
        description="Description of current scene"
    )


class WorldState(BaseModel):
    """Current state of the story world."""

    character_locations: dict[str, str] = Field(
        default_factory=dict,
        description="character_id -> location_id mapping"
    )
    current_location: str = Field(default="", description="Current story location")
    flags: dict[str, Any] = Field(
        default_factory=dict,
        description="Story state flags"
    )

    class Config:
        arbitrary_types_allowed = True


class RenderState(BaseModel):
    """Visual information for image generation."""

    location_visual: str = Field(default="", description="Visual description of current location")
    characters_present: list[str] = Field(
        default_factory=list,
        description="Visual descriptions of characters in scene"
    )
    objects_visible: list[str] = Field(
        default_factory=list,
        description="Visual descriptions of visible objects"
    )
    current_action: str = Field(
        default="",
        description="Visual description of what's happening"
    )
    mood: str = Field(default="neutral", description="Scene mood")
    time_of_day: str = Field(default="day", description="day, night, dawn, dusk")
    weather: str = Field(default="clear", description="Weather conditions")

    def to_image_prompt(self, visual_style: str = "comic book style") -> str:
        """Generate an image prompt from the render state."""
        parts = [visual_style]

        if self.location_visual:
            parts.append(f"Setting: {self.location_visual}")

        if self.time_of_day:
            parts.append(f"Time: {self.time_of_day}")

        if self.weather and self.weather != "clear":
            parts.append(f"Weather: {self.weather}")

        if self.characters_present:
            chars = ", ".join(self.characters_present[:3])
            parts.append(f"Characters: {chars}")

        if self.current_action:
            parts.append(f"Action: {self.current_action}")

        if self.mood:
            parts.append(f"Mood: {self.mood}")

        return ". ".join(parts)


class MetaInfo(BaseModel):
    """Technical metadata for the session."""

    session_id: str = Field(default="", description="Unique session identifier")
    panel_count: int = Field(default=0, description="Number of panels created")
    started_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)


class GameState(BaseModel):
    """Complete state for a comic creation session."""

    narrative: NarrativeState = Field(default_factory=NarrativeState)
    world: WorldState = Field(default_factory=WorldState)
    render: RenderState = Field(default_factory=RenderState)
    meta: MetaInfo = Field(default_factory=MetaInfo)

    @classmethod
    def initialize_from_config(cls, config: StaticConfig, session_id: str = "") -> "GameState":
        """Create initial state from configuration."""
        import uuid

        if not config.world_blueprint:
            raise ValueError("Cannot initialize without world blueprint")

        blueprint = config.world_blueprint

        # Initialize world state
        world = WorldState(
            character_locations={},
            current_location=blueprint.starting_location_id,
            flags={}
        )

        # Set character locations
        for char in blueprint.characters:
            world.character_locations[char.id] = char.location_id

        # Initialize narrative state
        starting_loc = config.get_location_by_id(blueprint.starting_location_id)
        scene_desc = starting_loc.description if starting_loc else "An unknown place."

        narrative = NarrativeState(
            panels=[],
            rolling_summary=f"{blueprint.synopsis}",
            current_scene=scene_desc
        )

        # Initialize render state
        render = RenderState(
            location_visual=starting_loc.visual_description if starting_loc else "",
            characters_present=[],
            objects_visible=[],
            current_action="The scene opens",
            mood="curious",
            time_of_day="day",
            weather="clear"
        )

        # Find characters at starting location
        for char in blueprint.characters:
            if char.location_id == blueprint.starting_location_id and char.role != "player":
                render.characters_present.append(f"{char.name}: {char.description}")

        # Meta info
        meta = MetaInfo(
            session_id=session_id or str(uuid.uuid4()),
            panel_count=0,
            started_at=datetime.now(),
            last_updated=datetime.now()
        )

        return cls(
            narrative=narrative,
            world=world,
            render=render,
            meta=meta
        )

    def add_panel(self, player_action: str, narrative: str, image_path: str | None = None) -> ComicPanel:
        """Add a new panel to the comic strip."""
        self.meta.panel_count += 1
        panel = ComicPanel(
            panel_number=self.meta.panel_count,
            narrative=narrative,
            image_path=image_path,
            player_action=player_action
        )
        self.narrative.panels.append(panel)
        self.meta.last_updated = datetime.now()
        return panel

    def get_recent_panels(self, count: int = 5) -> list[ComicPanel]:
        """Get the most recent panels."""
        return self.narrative.panels[-count:]

    def get_all_panels(self) -> list[ComicPanel]:
        """Get all panels in the comic strip."""
        return self.narrative.panels

    def get_context_summary(self) -> str:
        """Get a summary of current state for the LLM."""
        lines = [
            f"CURRENT STORY STATE (Panel {self.meta.panel_count}):",
            f"",
            f"Current Location: {self.world.current_location}",
            f"",
            f"Story So Far: {self.narrative.rolling_summary}",
            f"",
            f"Current Scene: {self.narrative.current_scene}",
        ]

        if self.narrative.panels:
            lines.append("")
            lines.append("Recent Panels:")
            for panel in self.get_recent_panels(3):
                lines.append(f"  Panel {panel.panel_number}: {panel.narrative[:100]}...")

        return "\n".join(lines)

    def save_to_file(self, filepath: str | Path) -> None:
        """Save state to a JSON file."""
        filepath = Path(filepath)
        with open(filepath, "w") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2, default=str)

    @classmethod
    def load_from_file(cls, filepath: str | Path) -> "GameState":
        """Load state from a JSON file."""
        filepath = Path(filepath)
        with open(filepath) as f:
            data = json.load(f)
        return cls.model_validate(data)
