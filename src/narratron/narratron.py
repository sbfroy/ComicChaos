"""NARRATRON - The comic creation engine.

The LLM has creative control over the story, dynamically introducing
locations and characters while maintaining consistency.
"""

import json
import os

from openai import OpenAI

from ..config import LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
from ..state.comic_state import ComicState, RenderState, DynamicLocation, DynamicCharacter
from ..state.static_config import StaticConfig
from .prompts import NARRATRON_SYSTEM_PROMPT, INITIAL_SCENE_PROMPT

class NarratronResponse:
    """Structured response from NARRATRON."""

    def __init__(self, raw_response: dict):
        self.raw = raw_response

        # Core narrative
        self.interpretation = raw_response.get("interpretation", "")
        self.panel_narrative = raw_response.get("panel_narrative", "")

        # Dynamic entity creation
        self.new_location = raw_response.get("new_location")  # dict or None
        self.new_character = raw_response.get("new_character")  # dict or None

        # State changes
        self.state_changes = raw_response.get("state_changes", {})
        self.visual_summary = raw_response.get("visual_summary", {})
        self.rolling_summary_update = raw_response.get("rolling_summary_update", "")
        self.current_scene = raw_response.get("current_scene", "")


class Narratron:
    """Narratron is the AI engine that orchestrates the comic creation.

    Narratron is the creative driver - it introduces new locations and characters
    as the story needs them, and validates user inputs against the comic's logic.
    """

    def __init__(
        self,
        config: StaticConfig,
        api_key: str | None = None
    ):
        self.config = config
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    def _build_system_prompt(self, comic_state: ComicState) -> str:
        """
        Build the system prompt with current context.
        
        Args:
            comic_state (ComicState): The current state of the comic.
        
        Returns:
            str: The formatted system prompt.
        """

        comic_context_parts = [] # List to build context string part by part

        bp = self.config.blueprint

        comic_context_parts.append(f"COMIC TITLE: {bp.title}")
        comic_context_parts.append(f"SYNOPSIS: {bp.synopsis}")
        comic_context_parts.append("") # Blank line for spacing

        # Main character (from blueprint)
        comic_context_parts.append("MAIN CHARACTER:")
        comic_context_parts.append(
            f"  {comic_state.world.main_character_name}: {comic_state.world.main_character_description}"
        )
        comic_context_parts.append("")

        # Known locations (dynamically created)
        comic_context_parts.append("KNOWN LOCATIONS:")
        for loc in comic_state.world.locations:
            comic_context_parts.append(f"  - {loc.name} ({loc.id}): {loc.description[:100]}...")
        comic_context_parts.append("")

        # Known characters (dynamically created)
        if comic_state.world.characters:
            comic_context_parts.append("CHARACTERS IN STORY:")
            for char in comic_state.world.characters:
                loc_info = f" [at: {char.current_location}]" if char.current_location else ""
                comic_context_parts.append(f"  - {char.name} ({char.id}): {char.description[:80]}...{loc_info}")
            comic_context_parts.append("")

        comic_context = "\n".join(comic_context_parts)

        visual_style = self.config.blueprint.visual_style 
        
        rules = "\n".join(f"- {rule}" for rule in self.config.blueprint.rules)

        return NARRATRON_SYSTEM_PROMPT.format(
            visual_style=visual_style,
            rules=rules,
            comic_context=f"CURRENT COMIC STATE:\n{comic_context}"
        )

    def _call_llm(self, messages: list[dict]) -> str:
        """Make an API call to the LLM."""
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
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

    def process_input(self, user_input: str, comic_state: ComicState) -> NarratronResponse:
        """Process user input and create the next comic panel."""
        system_prompt = self._build_system_prompt(comic_state)
        context = comic_state.get_context_summary()

        user_message = f"""CURRENT STORY STATE:
{context}

USER WANTS: {user_input}

Create the next comic panel based on what the user wants to happen.
Remember: Say YES to creative ideas! Introduce new characters/locations when needed."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes (including new entities)
        self._apply_state_changes(response, comic_state)

        return response

    def _apply_state_changes(self, response: NarratronResponse, comic_state: ComicState) -> None:
        """Apply state changes from the response, including new entities."""
        changes = response.state_changes

        # Add new location if introduced
        if response.new_location:
            new_loc = response.new_location
            description = new_loc.get("description", "")
            location = DynamicLocation(
                id=new_loc.get("id", f"loc_{comic_state.meta.panel_count}"),
                name=new_loc.get("name", "Unknown Location"),
                description=description,
                visual_description=description,
                first_appeared_panel=comic_state.meta.panel_count + 1
            )
            comic_state.world.add_location(location)

        # Add new character if introduced
        if response.new_character:
            new_char = response.new_character
            character = DynamicCharacter(
                id=new_char.get("id", f"char_{comic_state.meta.panel_count}"),
                name=new_char.get("name", "Unknown Character"),
                description=new_char.get("description", ""),
                current_location=comic_state.world.current_location_id,
                first_appeared_panel=comic_state.meta.panel_count + 1
            )
            comic_state.world.add_character(character)

        # Update current location
        if changes.get("current_location_id"):
            comic_state.world.current_location_id = changes["current_location_id"]

        if changes.get("current_location_name"):
            comic_state.world.current_location_name = changes["current_location_name"]

        # Update character locations based on who's present
        characters_present = changes.get("characters_present_ids", [])
        for char_id in characters_present:
            char = comic_state.world.get_character_by_id(char_id)
            if char:
                char.current_location = comic_state.world.current_location_id

        # Set flags
        for flag, value in changes.get("flags_set", {}).items():
            comic_state.world.flags[flag] = value

        # Update narrative
        if response.rolling_summary_update:
            comic_state.narrative.rolling_summary = response.rolling_summary_update

        if response.current_scene:
            comic_state.narrative.current_scene = response.current_scene

        # Update render state
        vs = response.visual_summary
        if vs:
            comic_state.render = RenderState(
                location_visual=vs.get("location_visual", comic_state.render.location_visual),
                characters_present=vs.get("characters_present", comic_state.render.characters_present),
                objects_visible=vs.get("objects_visible", comic_state.render.objects_visible),
                current_action=vs.get("current_action", comic_state.render.current_action)
            )

    def generate_opening_panel(self, comic_state: ComicState) -> NarratronResponse:
        """Generate the opening panel of the comic."""
        if not self.config.blueprint:
            raise ValueError("Cannot generate opening without blueprint")

        bp = self.config.blueprint
        starting_loc = bp.starting_location
        main_char = bp.main_character

        system_prompt = self._build_system_prompt(comic_state)

        user_message = INITIAL_SCENE_PROMPT.format(
            starting_location=f"{starting_loc.name}: {starting_loc.description}",
            main_character=f"{main_char.name}: {main_char.description}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes
        self._apply_state_changes(response, comic_state)

        return response
