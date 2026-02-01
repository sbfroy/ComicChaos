"""Dynamic state for comic creation sessions.

This module manages the evolving state of a comic creation session.
The LLM drives the story forward, with continuity maintained through
the rolling summary and recent panel history.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .static_config import StaticConfig


class ComicPanel(BaseModel):
    """A single panel in the comic strip."""

    panel_number: int = Field(description="Panel number in sequence")
    narrative: str = Field(description="The narrative text for this panel")
    image_path: str | None = Field(default=None, description="Path to generated image")
    is_auto: bool = Field(default=False, description="Whether this is an automatic transition panel")


class StoryGoals(BaseModel):
    """Internal story direction tracking."""

    short_term: list[str] = Field(
        default_factory=list,
        description="Goals for the next 1-3 panels, responsive to recent user input"
    )
    long_term: list[str] = Field(
        default_factory=list,
        description="Broader arc goals: character development, plot progression"
    )


class NarrativeState(BaseModel):
    """Record of the comic story."""

    panels: list[ComicPanel] = Field(default_factory=list)
    rolling_summary: str = Field(
        default="The comic has just begun.",
        description="Short summary of the comic so far"
    )
    goals: StoryGoals = Field(default_factory=StoryGoals)


class RenderState(BaseModel):
    """Scene information for image generation. Combined with the comic's visual_style."""

    scene_setting: str = Field(default="", description="Description of the current scene/location")
    characters_present: list[str] = Field(
        default_factory=list,
        description="Characters in the scene with brief descriptions"
    )
    current_action: str = Field(
        default="",
        description="What is happening in this panel"
    )


class MetaInfo(BaseModel):
    """Technical metadata for the session."""

    panel_count: int = Field(default=0, description="Number of panels created")
    last_updated: datetime = Field(default_factory=datetime.now)


class ComicState(BaseModel):
    """Complete state for a comic creation session."""

    narrative: NarrativeState = Field(default_factory=NarrativeState)
    render: RenderState = Field(default_factory=RenderState)
    meta: MetaInfo = Field(default_factory=MetaInfo)
    main_character_name: str = Field(default="", description="Name of the main character")
    main_character_description: str = Field(default="", description="Description of the main character")

    @classmethod
    def initialize_from_config(cls, config: StaticConfig) -> "ComicState":
        """Create initial state from configuration."""
        if not config.blueprint:
            raise ValueError("Cannot initialize without blueprint")

        blueprint = config.blueprint
        starting_loc = blueprint.starting_location
        main_char = blueprint.main_character

        goals = StoryGoals(
            long_term=blueprint.long_term_goals if blueprint.long_term_goals else []
        )

        narrative = NarrativeState(
            panels=[],
            rolling_summary=f"{blueprint.synopsis}",
            goals=goals,
        )

        render = RenderState(
            scene_setting=starting_loc.description,
            characters_present=[f"{main_char.name}: {main_char.description}"],
            current_action="The scene opens"
        )

        meta = MetaInfo(
            panel_count=0,
            last_updated=datetime.now()
        )

        return cls(
            narrative=narrative,
            render=render,
            meta=meta,
            main_character_name=main_char.name,
            main_character_description=main_char.description,
        )

    def add_panel(self, narrative: str, image_path: str | None = None) -> ComicPanel:
        """Add a new panel to the comic strip."""
        self.meta.panel_count += 1
        panel = ComicPanel(
            panel_number=self.meta.panel_count,
            narrative=narrative,
            image_path=image_path
        )
        self.narrative.panels.append(panel)
        self.meta.last_updated = datetime.now()
        return panel

    def get_recent_panels(self, count: int = 5) -> list[ComicPanel]:
        """Get the most recent panels."""
        return self.narrative.panels[-count:]
