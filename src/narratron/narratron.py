"""NARRATRON - The AI game orchestrator."""

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
        self.is_valid = raw_response.get("is_valid", True)
        self.constraint_violated = raw_response.get("constraint_violated")
        self.outcome_narrative = raw_response.get("outcome_narrative", "")
        self.milestone_completed = raw_response.get("milestone_completed")
        self.state_changes = raw_response.get("state_changes", {})
        self.visual_summary = raw_response.get("visual_summary", {})
        self.rolling_summary_update = raw_response.get("rolling_summary_update", "")
        self.current_scene = raw_response.get("current_scene", "")


class Narratron:
    """The AI orchestrator that controls all game logic."""

    def __init__(
        self,
        config: StaticConfig,
        api_key: str | None = None,
        model: str = "gpt-4o-mini" # gpt-4o
    ):
        self.config = config
        self.model = model
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self._conversation_history: list[dict] = []

    def _build_system_prompt(self, game_state: GameState) -> str:
        """Build the system prompt with current context."""
        # Get world context from config and state
        world_context_parts = []

        if self.config.world_blueprint:
            bp = self.config.world_blueprint
            world_context_parts.append(f"GAME TITLE: {bp.title}")
            world_context_parts.append(f"SETTING: {bp.setting}")
            world_context_parts.append(f"PLAYER'S GOAL: {bp.goal}")
            world_context_parts.append("")

            # Locations
            world_context_parts.append("LOCATIONS:")
            for loc in bp.locations:
                accessible = "accessible" if loc.id in game_state.world.accessible_locations else "locked"
                discovered = "(discovered)" if loc.id in game_state.world.discovered_locations else "(unknown)"
                world_context_parts.append(f"  - {loc.name} ({loc.id}): {loc.description[:100]}... [{accessible}] {discovered}")
                if loc.connections:
                    connections = ", ".join([f"{d}->{lid}" for d, lid in loc.connections.items()])
                    world_context_parts.append(f"    Connections: {connections}")
            world_context_parts.append("")

            # Characters
            world_context_parts.append("CHARACTERS:")
            for char in bp.characters:
                current_loc = game_state.world.character_locations.get(char.id, char.location_id)
                world_context_parts.append(f"  - {char.name} ({char.id}): {char.description[:80]}... [at: {current_loc}]")
                if char.abilities:
                    world_context_parts.append(f"    Abilities: {', '.join(char.abilities)}")
            world_context_parts.append("")

            # Items
            world_context_parts.append("ITEMS:")
            for item in bp.items:
                loc = game_state.world.item_locations.get(item.id, item.location_id)
                owner = game_state.world.item_owners.get(item.id, item.owner_id)
                loc_str = f"at {loc}" if loc else f"owned by {owner}" if owner else "unknown"
                if item.id in game_state.player.inventory:
                    loc_str = "in player inventory"
                world_context_parts.append(f"  - {item.name} ({item.id}): {item.description[:60]}... [{loc_str}]")

        world_context = "\n".join(world_context_parts)

        return NARRATRON_SYSTEM_PROMPT.format(
            constraints=self.config.get_constraints_summary(),
            milestones=self.config.get_milestones_summary(),
            world_context=f"WORLD INFORMATION:\n{world_context}"
        )

    def _call_llm(self, messages: list[dict]) -> str:
        """Make an API call to the LLM."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=1500,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    def _parse_response(self, response_text: str) -> NarratronResponse:
        """Parse the LLM response into a structured format."""
        try:
            data = json.loads(response_text)
            return NarratronResponse(data)
        except json.JSONDecodeError:
            # If parsing fails, create a default error response
            return NarratronResponse({
                "interpretation": "Unknown action",
                "is_valid": False,
                "outcome_narrative": "Something went wrong processing your action. Please try again.",
                "state_changes": {},
                "visual_summary": {}
            })

    def process_action(self, player_action: str, game_state: GameState) -> NarratronResponse:
        """Process a player action and return the NARRATRON's response."""
        system_prompt = self._build_system_prompt(game_state)
        context = game_state.get_context_summary()

        # Build the user message
        user_message = f"""CURRENT GAME STATE:
{context}

PLAYER ACTION: {player_action}

Process this action according to the rules and respond with the required JSON format."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        # Call the LLM
        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes to game state
        self._apply_state_changes(response, game_state)

        return response

    def _apply_state_changes(self, response: NarratronResponse, game_state: GameState) -> None:
        """Apply the state changes from NARRATRON to the game state."""
        changes = response.state_changes

        # Update player location
        if changes.get("player_location"):
            new_loc = changes["player_location"]
            game_state.player.location_id = new_loc
            game_state.world.discovered_locations.add(new_loc)

        # Update inventory
        for item_id in changes.get("items_gained", []):
            if item_id not in game_state.player.inventory:
                game_state.player.inventory.append(item_id)
            game_state.world.item_locations[item_id] = None
            game_state.world.item_owners[item_id] = "player"

        for item_id in changes.get("items_lost", []):
            if item_id in game_state.player.inventory:
                game_state.player.inventory.remove(item_id)

        # Update flags
        for flag, value in changes.get("flags_set", {}).items():
            game_state.world.flags[flag] = value

        # Update variables
        for var, value in changes.get("variables_changed", {}).items():
            game_state.world.variables[var] = value

        # Move characters
        for char_id, new_loc in changes.get("characters_moved", {}).items():
            game_state.world.character_locations[char_id] = new_loc

        # Add new information
        for info in changes.get("new_information", []):
            if info not in game_state.player.known_information:
                game_state.player.known_information.append(info)

        # Update health
        health_change = changes.get("health_change", 0)
        game_state.player.health = max(0, min(100, game_state.player.health + health_change))

        # Update milestone progress
        if response.milestone_completed:
            game_state.checkpoints.complete_milestone(response.milestone_completed)
            # Find next milestone
            for milestone in self.config.get_milestones_in_order():
                if not game_state.checkpoints.is_completed(milestone.id):
                    game_state.checkpoints.current_milestone_id = milestone.id
                    break
            else:
                game_state.checkpoints.current_milestone_id = None

        # Update narrative
        game_state.add_event(
            player_action=response.interpretation,
            outcome=response.outcome_narrative
        )

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

    def generate_opening_scene(self, game_state: GameState) -> NarratronResponse:
        """Generate the opening scene of the game."""
        if not self.config.world_blueprint:
            raise ValueError("Cannot generate opening scene without world blueprint")

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

        # Apply state changes (mainly visual summary)
        self._apply_state_changes(response, game_state)

        return response

    def get_current_milestone_hint(self, game_state: GameState) -> str | None:
        """Get a hint for the current milestone."""
        if not game_state.checkpoints.current_milestone_id:
            return None

        milestone = self.config.get_milestone_by_id(game_state.checkpoints.current_milestone_id)
        return milestone.hint if milestone else None
