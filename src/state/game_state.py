"""Dynamic game state that evolves during gameplay."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from .static_config import StaticConfig


class NarrativeEvent(BaseModel):
    """A single event in the narrative history."""

    turn: int = Field(description="Turn number when this event occurred")
    player_action: str = Field(description="What the player attempted to do")
    outcome: str = Field(description="What actually happened")
    timestamp: datetime = Field(default_factory=datetime.now)


class NarrativeState(BaseModel):
    """Record of what has happened in the story."""

    events: list[NarrativeEvent] = Field(default_factory=list)
    rolling_summary: str = Field(
        default="The story has just begun.",
        description="Condensed summary of key events for context efficiency"
    )
    current_scene: str = Field(
        default="",
        description="Description of what's currently happening"
    )


class WorldState(BaseModel):
    """Current state of the game world."""

    character_locations: dict[str, str] = Field(
        default_factory=dict,
        description="character_id -> location_id mapping"
    )
    discovered_locations: set[str] = Field(
        default_factory=set,
        description="Set of location IDs the player has discovered"
    )
    accessible_locations: set[str] = Field(
        default_factory=set,
        description="Set of location IDs currently accessible"
    )
    flags: dict[str, bool] = Field(
        default_factory=dict,
        description="Game flags for tracking state"
    )
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom variables for puzzles and mechanics"
    )
    item_locations: dict[str, str | None] = Field(
        default_factory=dict,
        description="item_id -> location_id (None if in inventory)"
    )
    item_owners: dict[str, str | None] = Field(
        default_factory=dict,
        description="item_id -> character_id who owns it"
    )

    class Config:
        arbitrary_types_allowed = True

    def model_dump(self, **kwargs) -> dict:
        """Custom serialization to handle sets."""
        data = super().model_dump(**kwargs)
        data["discovered_locations"] = list(data["discovered_locations"])
        data["accessible_locations"] = list(data["accessible_locations"])
        return data

    @classmethod
    def model_validate(cls, obj: Any) -> "WorldState":
        """Custom deserialization to handle sets."""
        if isinstance(obj, dict):
            obj = obj.copy()
            if "discovered_locations" in obj:
                obj["discovered_locations"] = set(obj["discovered_locations"])
            if "accessible_locations" in obj:
                obj["accessible_locations"] = set(obj["accessible_locations"])
        return super().model_validate(obj)


class PlayerState(BaseModel):
    """Current state of the player character."""

    location_id: str = Field(description="Current location")
    inventory: list[str] = Field(default_factory=list, description="Item IDs in inventory")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Player attributes")
    known_information: list[str] = Field(
        default_factory=list,
        description="Information the player has learned"
    )
    health: int = Field(default=100, description="Player health")
    status_effects: list[str] = Field(default_factory=list, description="Active status effects")


class CheckpointProgress(BaseModel):
    """Tracks progress through milestones."""

    completed_milestones: list[str] = Field(
        default_factory=list,
        description="IDs of completed milestones"
    )
    current_milestone_id: str | None = Field(
        default=None,
        description="The next milestone to achieve"
    )
    milestone_timestamps: dict[str, datetime] = Field(
        default_factory=dict,
        description="When each milestone was completed"
    )

    def is_completed(self, milestone_id: str) -> bool:
        """Check if a milestone is completed."""
        return milestone_id in self.completed_milestones

    def complete_milestone(self, milestone_id: str) -> None:
        """Mark a milestone as completed."""
        if milestone_id not in self.completed_milestones:
            self.completed_milestones.append(milestone_id)
            self.milestone_timestamps[milestone_id] = datetime.now()


class RenderState(BaseModel):
    """Visual-only information for image generation."""

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
    mood: str = Field(default="neutral", description="Scene mood: tense, calm, action, mysterious")
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
            chars = ", ".join(self.characters_present[:3])  # Limit characters
            parts.append(f"Characters: {chars}")

        if self.current_action:
            parts.append(f"Action: {self.current_action}")

        if self.mood:
            parts.append(f"Mood: {self.mood}")

        return ". ".join(parts)


class MetaInfo(BaseModel):
    """Technical metadata for the game session."""

    session_id: str = Field(default="", description="Unique session identifier")
    turn_count: int = Field(default=0, description="Number of turns taken")
    started_at: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    engine_version: str = Field(default="0.1.0")


class GameState(BaseModel):
    """Complete dynamic game state."""

    narrative: NarrativeState = Field(default_factory=NarrativeState)
    world: WorldState = Field(default_factory=WorldState)
    player: PlayerState = Field(default_factory=lambda: PlayerState(location_id=""))
    checkpoints: CheckpointProgress = Field(default_factory=CheckpointProgress)
    render: RenderState = Field(default_factory=RenderState)
    meta: MetaInfo = Field(default_factory=MetaInfo)

    @classmethod
    def initialize_from_config(cls, config: StaticConfig, session_id: str = "") -> "GameState":
        """Create initial game state from static configuration."""
        import uuid

        if not config.world_blueprint:
            raise ValueError("Cannot initialize game state without world blueprint")

        blueprint = config.world_blueprint

        # Initialize player state
        player = PlayerState(
            location_id=blueprint.starting_location_id,
            inventory=[],
            attributes={},
            known_information=[]
        )

        # Initialize world state
        world = WorldState(
            character_locations={},
            discovered_locations={blueprint.starting_location_id},
            accessible_locations=set(),
            flags={},
            variables={},
            item_locations={},
            item_owners={}
        )

        # Set character locations
        for char in blueprint.characters:
            world.character_locations[char.id] = char.location_id

        # Set accessible locations
        for loc in blueprint.locations:
            if loc.accessible:
                world.accessible_locations.add(loc.id)

        # Set item locations and owners
        for item in blueprint.items:
            if item.location_id:
                world.item_locations[item.id] = item.location_id
            if item.owner_id:
                world.item_owners[item.id] = item.owner_id

        # Initialize narrative state
        starting_loc = config.get_location_by_id(blueprint.starting_location_id)
        scene_desc = starting_loc.description if starting_loc else "You find yourself in an unknown place."

        narrative = NarrativeState(
            events=[],
            rolling_summary=f"The story begins. {blueprint.synopsis}",
            current_scene=scene_desc
        )

        # Initialize render state
        render = RenderState(
            location_visual=starting_loc.visual_description if starting_loc else "",
            characters_present=[],
            objects_visible=[],
            current_action="standing, looking around",
            mood="curious",
            time_of_day="day",
            weather="clear"
        )

        # Find characters at starting location
        for char in blueprint.characters:
            if char.location_id == blueprint.starting_location_id and char.role != "player":
                render.characters_present.append(f"{char.name}: {char.description}")

        # Initialize checkpoint progress
        milestones = config.get_milestones_in_order()
        first_milestone_id = milestones[0].id if milestones else None

        checkpoints = CheckpointProgress(
            completed_milestones=[],
            current_milestone_id=first_milestone_id
        )

        # Meta info
        meta = MetaInfo(
            session_id=session_id or str(uuid.uuid4()),
            turn_count=0,
            started_at=datetime.now(),
            last_updated=datetime.now(),
            engine_version="0.1.0"
        )

        return cls(
            narrative=narrative,
            world=world,
            player=player,
            checkpoints=checkpoints,
            render=render,
            meta=meta
        )

    def add_event(self, player_action: str, outcome: str) -> None:
        """Add a new narrative event."""
        event = NarrativeEvent(
            turn=self.meta.turn_count,
            player_action=player_action,
            outcome=outcome
        )
        self.narrative.events.append(event)
        self.meta.turn_count += 1
        self.meta.last_updated = datetime.now()

    def get_recent_events(self, count: int = 5) -> list[NarrativeEvent]:
        """Get the most recent events."""
        return self.narrative.events[-count:]

    def get_context_summary(self) -> str:
        """Get a summary of current game state for the NARRATRON."""
        lines = [
            f"CURRENT GAME STATE (Turn {self.meta.turn_count}):",
            f"",
            f"Player Location: {self.player.location_id}",
            f"Player Inventory: {', '.join(self.player.inventory) if self.player.inventory else 'empty'}",
            f"",
            f"Story So Far: {self.narrative.rolling_summary}",
            f"",
            f"Current Scene: {self.narrative.current_scene}",
            f"",
            f"Completed Milestones: {', '.join(self.checkpoints.completed_milestones) if self.checkpoints.completed_milestones else 'none'}",
            f"Current Objective: {self.checkpoints.current_milestone_id or 'none'}",
        ]

        if self.narrative.events:
            lines.append("")
            lines.append("Recent Events:")
            for event in self.get_recent_events(3):
                lines.append(f"  - Player: {event.player_action}")
                lines.append(f"    Result: {event.outcome}")

        return "\n".join(lines)

    def save_to_file(self, filepath: str | Path) -> None:
        """Save game state to a JSON file."""
        filepath = Path(filepath)
        with open(filepath, "w") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2, default=str)

    @classmethod
    def load_from_file(cls, filepath: str | Path) -> "GameState":
        """Load game state from a JSON file."""
        filepath = Path(filepath)
        with open(filepath) as f:
            data = json.load(f)
        return cls.model_validate(data)
