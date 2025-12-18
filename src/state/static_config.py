"""Static configuration for game rules, milestones, and world blueprint."""

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class Constraint(BaseModel):
    """A non-negotiable rule that governs the world's logic."""

    id: str = Field(description="Unique identifier for this constraint")
    description: str = Field(description="Human-readable description of the constraint")
    rule: str = Field(description="The rule in natural language for the NARRATRON to enforce")
    category: str = Field(default="general", description="Category: physical, social, technological, access")


class Milestone(BaseModel):
    """A mandatory story checkpoint that guides narrative progression."""

    id: str = Field(description="Unique identifier for this milestone")
    name: str = Field(description="Display name of the milestone")
    description: str = Field(description="What this milestone represents in the story")
    condition: str = Field(description="Natural language condition for when this milestone is achieved")
    order: int = Field(description="Order in the narrative progression (lower = earlier)")
    prerequisite_ids: list[str] = Field(default_factory=list, description="IDs of milestones that must be completed first")
    hint: str = Field(default="", description="Optional hint to guide the player")


class Character(BaseModel):
    """A character in the game world."""

    id: str = Field(description="Unique identifier")
    name: str = Field(description="Character's name")
    description: str = Field(description="Physical and personality description")
    location_id: str = Field(description="Starting location ID")
    role: str = Field(default="npc", description="Role: player, npc, antagonist, ally")
    abilities: list[str] = Field(default_factory=list, description="Special abilities or skills")
    inventory: list[str] = Field(default_factory=list, description="Items the character starts with")


class Item(BaseModel):
    """An interactable item in the game world."""

    id: str = Field(description="Unique identifier")
    name: str = Field(description="Item name")
    description: str = Field(description="Physical description")
    location_id: str | None = Field(default=None, description="Location ID or None if in character inventory")
    owner_id: str | None = Field(default=None, description="Character ID who owns this, if any")
    usable: bool = Field(default=True, description="Can this item be used?")
    takeable: bool = Field(default=True, description="Can this item be picked up?")
    properties: dict[str, Any] = Field(default_factory=dict, description="Custom properties")


class Location(BaseModel):
    """A location in the game world."""

    id: str = Field(description="Unique identifier")
    name: str = Field(description="Location name")
    description: str = Field(description="Detailed description of the location")
    visual_description: str = Field(default="", description="Concise visual description for image generation")
    connections: dict[str, str] = Field(default_factory=dict, description="Direction -> location_id mapping")
    accessible: bool = Field(default=True, description="Is this location accessible from the start?")
    access_condition: str = Field(default="", description="Condition to unlock if not accessible")


class WorldBlueprint(BaseModel):
    """The initial state of the game world."""

    title: str = Field(description="Game/story title")
    synopsis: str = Field(description="Brief story synopsis for context")
    setting: str = Field(description="Overall setting description")
    starting_location_id: str = Field(description="Where the player begins")
    goal: str = Field(description="The player's ultimate objective")
    locations: list[Location] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    visual_style: str = Field(
        default="comic book style, vibrant colors, dynamic panels",
        description="Art style for generated images"
    )


class StaticConfig(BaseModel):
    """Complete static game configuration."""

    constraints: list[Constraint] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    world_blueprint: WorldBlueprint | None = None

    @classmethod
    def load_from_directory(cls, config_dir: str | Path) -> "StaticConfig":
        """Load static configuration from JSON files in a directory."""
        config_dir = Path(config_dir)

        constraints = []
        milestones = []
        world_blueprint = None

        constraints_file = config_dir / "constraints.json"
        if constraints_file.exists():
            with open(constraints_file) as f:
                data = json.load(f)
                constraints = [Constraint(**c) for c in data.get("constraints", [])]

        milestones_file = config_dir / "milestones.json"
        if milestones_file.exists():
            with open(milestones_file) as f:
                data = json.load(f)
                milestones = [Milestone(**m) for m in data.get("milestones", [])]

        blueprint_file = config_dir / "world_blueprint.json"
        if blueprint_file.exists():
            with open(blueprint_file) as f:
                data = json.load(f)
                world_blueprint = WorldBlueprint(**data)

        return cls(
            constraints=constraints,
            milestones=milestones,
            world_blueprint=world_blueprint
        )

    def get_constraint_by_id(self, constraint_id: str) -> Constraint | None:
        """Get a constraint by its ID."""
        for c in self.constraints:
            if c.id == constraint_id:
                return c
        return None

    def get_milestone_by_id(self, milestone_id: str) -> Milestone | None:
        """Get a milestone by its ID."""
        for m in self.milestones:
            if m.id == milestone_id:
                return m
        return None

    def get_milestones_in_order(self) -> list[Milestone]:
        """Get milestones sorted by their order."""
        return sorted(self.milestones, key=lambda m: m.order)

    def get_location_by_id(self, location_id: str) -> Location | None:
        """Get a location from the world blueprint by ID."""
        if not self.world_blueprint:
            return None
        for loc in self.world_blueprint.locations:
            if loc.id == location_id:
                return loc
        return None

    def get_character_by_id(self, character_id: str) -> Character | None:
        """Get a character from the world blueprint by ID."""
        if not self.world_blueprint:
            return None
        for char in self.world_blueprint.characters:
            if char.id == character_id:
                return char
        return None

    def get_item_by_id(self, item_id: str) -> Item | None:
        """Get an item from the world blueprint by ID."""
        if not self.world_blueprint:
            return None
        for item in self.world_blueprint.items:
            if item.id == item_id:
                return item
        return None

    def get_constraints_summary(self) -> str:
        """Get a formatted summary of all constraints for the NARRATRON."""
        if not self.constraints:
            return "No constraints defined."

        lines = ["WORLD CONSTRAINTS (must always be enforced):"]
        for c in self.constraints:
            lines.append(f"- [{c.category.upper()}] {c.rule}")
        return "\n".join(lines)

    def get_milestones_summary(self) -> str:
        """Get a formatted summary of all milestones for the NARRATRON."""
        if not self.milestones:
            return "No milestones defined."

        lines = ["STORY MILESTONES (checkpoints to track):"]
        for m in self.get_milestones_in_order():
            prereqs = f" (requires: {', '.join(m.prerequisite_ids)})" if m.prerequisite_ids else ""
            lines.append(f"- [{m.order}] {m.name}: {m.condition}{prereqs}")
        return "\n".join(lines)
