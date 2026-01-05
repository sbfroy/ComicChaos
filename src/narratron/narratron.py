"""NARRATRON - The comic creation engine."""

import json
import os
from typing import Any

from openai import OpenAI

from ..state.game_state import GameState, RenderState
from ..state.static_config import StaticConfig
from .prompts import NARRATRON_SYSTEM_PROMPT, INITIAL_SCENE_PROMPT


class NarratronResponse:
    """Structured response from NARRATRON."""

    def __init__(self, raw_response: dict):
        self.raw = raw_response
        self.interpretation = raw_response.get("interpretation", "")
        self.panel_narrative = raw_response.get("panel_narrative", "")
        self.state_changes = raw_response.get("state_changes", {})
        self.visual_summary = raw_response.get("visual_summary", {})
        self.rolling_summary_update = raw_response.get("rolling_summary_update", "")
        self.current_scene = raw_response.get("current_scene", "")


class Narratron:
    """The AI engine that creates comic panels."""

    def __init__(
        self,
        config: StaticConfig,
        api_key: str | None = None,
        model: str = "gpt-4o-mini"
    ):
        self.config = config
        self.model = model
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    def _build_system_prompt(self, game_state: GameState) -> str:
        """Build the system prompt with current context."""
        world_context_parts = []

        if self.config.world_blueprint:
            bp = self.config.world_blueprint
            world_context_parts.append(f"COMIC TITLE: {bp.title}")
            world_context_parts.append(f"SETTING: {bp.setting}")
            world_context_parts.append(f"STORY CONCEPT: {bp.goal}")
            world_context_parts.append("")

            # Locations
            world_context_parts.append("LOCATIONS:")
            for loc in bp.locations:
                world_context_parts.append(f"  - {loc.name} ({loc.id}): {loc.description[:100]}...")
            world_context_parts.append("")

            # Characters
            world_context_parts.append("CHARACTERS:")
            for char in bp.characters:
                current_loc = game_state.world.character_locations.get(char.id, char.location_id)
                world_context_parts.append(f"  - {char.name} ({char.id}): {char.description[:80]}... [at: {current_loc}]")

        world_context = "\n".join(world_context_parts)
        visual_style = self.config.world_blueprint.visual_style if self.config.world_blueprint else "comic book style"

        return NARRATRON_SYSTEM_PROMPT.format(
            visual_style=visual_style,
            world_context=f"WORLD INFORMATION:\n{world_context}"
        )

    def _call_llm(self, messages: list[dict]) -> str:
        """Make an API call to the LLM."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
            max_tokens=1000,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    def _parse_response(self, response_text: str) -> NarratronResponse:
        """Parse the LLM response into a structured format."""
        try:
            data = json.loads(response_text)
            return NarratronResponse(data)
        except json.JSONDecodeError:
            return NarratronResponse({
                "interpretation": "Unknown",
                "panel_narrative": "Something unexpected happened...",
                "state_changes": {},
                "visual_summary": {}
            })

    def process_input(self, user_input: str, game_state: GameState) -> NarratronResponse:
        """Process user input and create the next comic panel."""
        system_prompt = self._build_system_prompt(game_state)
        context = game_state.get_context_summary()

        user_message = f"""CURRENT STORY STATE:
{context}

USER WANTS: {user_input}

Create the next comic panel based on what the user wants to happen."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes
        self._apply_state_changes(response, game_state)

        return response

    def _apply_state_changes(self, response: NarratronResponse, game_state: GameState) -> None:
        """Apply state changes from the response."""
        changes = response.state_changes

        # Update location
        if changes.get("current_location"):
            game_state.world.current_location = changes["current_location"]

        # Move characters
        for char_id, new_loc in changes.get("characters_moved", {}).items():
            game_state.world.character_locations[char_id] = new_loc

        # Set flags
        for flag, value in changes.get("flags_set", {}).items():
            game_state.world.flags[flag] = value

        # Update narrative
        if response.rolling_summary_update:
            game_state.narrative.rolling_summary = response.rolling_summary_update

        if response.current_scene:
            game_state.narrative.current_scene = response.current_scene

        # Update render state
        vs = response.visual_summary
        if vs:
            game_state.render = RenderState(
                location_visual=vs.get("location_visual", game_state.render.location_visual),
                characters_present=vs.get("characters_present", game_state.render.characters_present),
                objects_visible=vs.get("objects_visible", game_state.render.objects_visible),
                current_action=vs.get("current_action", game_state.render.current_action),
                mood=vs.get("mood", game_state.render.mood),
                time_of_day=vs.get("time_of_day", game_state.render.time_of_day),
                weather=vs.get("weather", game_state.render.weather)
            )

    def generate_opening_panel(self, game_state: GameState) -> NarratronResponse:
        """Generate the opening panel of the comic."""
        if not self.config.world_blueprint:
            raise ValueError("Cannot generate opening without world blueprint")

        bp = self.config.world_blueprint
        starting_loc = self.config.get_location_by_id(bp.starting_location_id)

        system_prompt = self._build_system_prompt(game_state)

        user_message = INITIAL_SCENE_PROMPT.format(
            starting_location=f"{starting_loc.name}: {starting_loc.description}" if starting_loc else "Unknown location",
            goal=bp.goal,
            setting=bp.setting
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes
        self._apply_state_changes(response, game_state)

        return response
