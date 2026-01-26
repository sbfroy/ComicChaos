"""NARRATRON - The comic creation engine.

This module contains the Narratron AI engine that orchestrates comic creation.
The LLM has creative control over the story, dynamically introducing locations
and characters while maintaining consistency with the comic's blueprint and rules.

Classes:
    NarratronResponse: Structured response container from NARRATRON.
    Narratron: The AI engine that orchestrates comic creation.
"""

import json
import os
from typing import Optional, Dict, List, Any

from openai import OpenAI

from pathlib import Path

from ..config import LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
from ..state.comic_state import (
    ComicState,
    RenderState,
    DynamicLocation,
    DynamicCharacter,
)
from ..state.static_config import StaticConfig
from ..logging.interaction_logger import InteractionLogger
from ..prompt_loader import load_prompt, load_json

_DIR = Path(__file__).parent
_PROMPTS_DIR = _DIR.parent / "prompts"

class NarratronResponse:
    """Structured response from NARRATRON.

    This class encapsulates all data returned by the NARRATRON AI engine,
    including scene description, panel elements, and state changes.

    Attributes:
        raw: The raw dictionary response from the LLM.
        scene_description: Visual description of what's happening (for image generation).
        elements: List of panel elements (speech bubbles, etc.) - most pre-filled, one for user input.
        new_location: Dictionary describing a newly introduced location (if any).
        new_character: Dictionary describing a newly introduced character (if any).
        state_changes: Dictionary of changes to apply to the comic state.
        scene_summary: Summary of the current scene for rendering.
        rolling_summary_update: Updated summary of the story so far.
    """

    def __init__(self, raw_response: Dict[str, Any]) -> None:
        """Initialize a NarratronResponse from raw LLM output.

        Args:
            raw_response: Dictionary containing the parsed JSON response from the LLM.
        """
        self.raw: Dict[str, Any] = raw_response

        # Scene description for image generation
        self.scene_description: str = raw_response.get("scene_description", "")

        # Panel elements - most pre-filled with text, one marked for user input
        self.elements: List[Dict[str, Any]] = raw_response.get("elements", [])

        # Dynamic entity creation (locations and characters)
        self.new_location: Optional[Dict[str, Any]] = raw_response.get("new_location")
        self.new_character: Optional[Dict[str, Any]] = raw_response.get("new_character")

        # State changes and scene information
        self.state_changes: Dict[str, Any] = raw_response.get("state_changes", {})
        self.scene_summary: Dict[str, Any] = raw_response.get("scene_summary", {})
        self.rolling_summary_update: str = raw_response.get("rolling_summary_update", "")


class Narratron:
    """The AI engine that orchestrates comic creation.

    Narratron is the creative driver behind the comic. It processes user inputs,
    generates narrative content, introduces new locations and characters as the
    story needs them, and maintains consistency with the comic's blueprint and rules.
    
    The engine uses an LLM to understand user intent and generate structured responses
    that include narrative text, scene descriptions, and state changes.
    
    Attributes:
        config: Static configuration containing the comic blueprint and rules.
        client: OpenAI client for making LLM API calls.
    """

    def __init__(
        self,
        config: StaticConfig,
        api_key: Optional[str] = None,
        logger: Optional[InteractionLogger] = None,
    ) -> None:
        """Initialize the Narratron engine.
        
        Args:
            config: Static configuration containing blueprint and rules.
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY environment variable.
            logger: Interaction logger for tracking prompts and responses.
        """
        self.config: StaticConfig = config
        self.client: OpenAI = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )
        self.logger: Optional[InteractionLogger] = logger

    def _build_system_prompt(self) -> str:
        """Build the system prompt with static comic information only.

        Creates a compact system prompt with just the essential static info:
        title, visual style, and rules. All dynamic context (locations,
        characters, panels) is provided in the user message to avoid duplication.

        Returns:
            The formatted system prompt string ready for the LLM.
        """
        blueprint = self.config.blueprint

        # Format rules compactly
        rules = " | ".join(self.config.blueprint.rules) if self.config.blueprint.rules else "None"

        return load_prompt(
            _PROMPTS_DIR / "narratron.system.md",
            title=blueprint.title,
            visual_style=blueprint.visual_style,
            rules=rules,
        )

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Make an API call to the LLM.
        
        Sends messages to the OpenAI API and returns the response content.
        Configured to return JSON-formatted responses for structured output.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys.
        
        Returns:
            The LLM's response content as a string (JSON format).
        """
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},  # Ensure structured JSON output
        )

        response_content = response.choices[0].message.content
        
        # Log the interaction if logger is available
        if self.logger:
            system_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_message = next((m["content"] for m in messages if m["role"] == "user"), "")
            
            # Try to parse response for logging
            parsed_response = None
            try:
                parsed_response = json.loads(response_content)
            except json.JSONDecodeError:
                pass
            
            self.logger.log_narrative_interaction(
                system_prompt=system_prompt,
                user_message=user_message,
                response=response_content,
                parsed_response=parsed_response,
                model=LLM_MODEL,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS
            )
        
        return response_content

    def _parse_response(self, response_text: str) -> NarratronResponse:
        """Parse the LLM response into a structured format.

        Attempts to parse the JSON response from the LLM. If parsing fails,
        returns a fallback response to gracefully handle errors.

        Args:
            response_text: The raw JSON string response from the LLM.

        Returns:
            A NarratronResponse object containing the parsed data.
        """
        try:
            data = json.loads(response_text)
            return NarratronResponse(data)
        except json.JSONDecodeError:
            # Fallback response if JSON parsing fails
            fallback_data = load_json(_DIR / "error_fallback.json")
            return NarratronResponse(fallback_data)

    def process_input(
        self, user_input: str, comic_state: ComicState
    ) -> NarratronResponse:
        """Process user input and create the next comic panel.

        This is the main entry point for generating new comic content. It takes
        the user's request, combines it with the current comic state, sends it
        to the LLM, and applies the resulting state changes.

        Args:
            user_input: The user's description of what they want to happen next.
            comic_state: The current state of the comic.

        Returns:
            A NarratronResponse containing the generated narrative and state changes.
        """
        # Build compact system prompt (static info only)
        system_prompt = self._build_system_prompt()

        # Build user message with all dynamic context
        user_message = self._build_user_message(user_input, comic_state)

        # Prepare messages for the LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Get response from LLM and parse it
        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes (including newly introduced entities)
        self._apply_state_changes(response, comic_state)

        return response

    def _build_user_message(self, user_input: str, comic_state: ComicState) -> str:
        """Build compact user message with all dynamic context.

        Constructs a token-efficient user message containing:
        - Main character info
        - Current location with full description
        - Story summary
        - Compact entity list (full desc only for entities in scene)
        - Recent panel summaries
        - User's request

        Args:
            user_input: What the user wants to happen.
            comic_state: Current comic state.

        Returns:
            Formatted user message string.
        """
        world = comic_state.world

        # Main character
        main_char = f"{world.main_character_name}: {world.main_character_description}"

        # Current location with full description
        current_loc = world.get_location_by_id(world.current_location_id)
        current_location = (
            f"{current_loc.name}: {current_loc.description}"
            if current_loc
            else world.current_location_name
        )

        # Build compact entities context
        entities_parts: List[str] = []

        # Locations: current gets full desc, others just name
        other_locations = [
            loc.name for loc in world.locations
            if loc.id != world.current_location_id
        ]
        if other_locations:
            entities_parts.append(f"OTHER LOCATIONS: {', '.join(other_locations)}")

        # Characters: those in scene get full desc, others compact
        if world.characters:
            chars_here = []
            chars_elsewhere = []
            for char in world.characters:
                if char.current_location == world.current_location_id:
                    chars_here.append(f"{char.name}: {char.description}")
                else:
                    loc_name = char.current_location or "unknown"
                    chars_elsewhere.append(f"{char.name} (at {loc_name})")

            if chars_here:
                entities_parts.append(f"CHARACTERS HERE: {'; '.join(chars_here)}")
            if chars_elsewhere:
                entities_parts.append(f"OTHER CHARACTERS: {', '.join(chars_elsewhere)}")

        entities_context = "\n".join(entities_parts) if entities_parts else ""

        # Recent panels (compact)
        recent_panels = ""
        if comic_state.narrative.panels:
            panel_lines = []
            for panel in comic_state.get_recent_panels(3):
                # Truncate long narratives
                narrative = panel.narrative[:150] + "..." if len(panel.narrative) > 150 else panel.narrative
                panel_lines.append(f"P{panel.panel_number}: {narrative}")
            recent_panels = "RECENT:\n" + "\n".join(panel_lines)

        return load_prompt(
            _PROMPTS_DIR / "panel.user.md",
            main_character=main_char,
            current_location=current_location,
            rolling_summary=comic_state.narrative.rolling_summary,
            entities_context=entities_context,
            recent_panels=recent_panels,
            user_input=user_input,
        )

    def _apply_state_changes(
        self, response: NarratronResponse, comic_state: ComicState
    ) -> None:
        """Apply state changes from the response, including new entities.

        Processes the response from the LLM and updates the comic state accordingly.
        This includes adding new locations and characters, updating the current scene,
        moving characters between locations, and updating narrative summaries.

        Args:
            response: The parsed response from NARRATRON containing state changes.
            comic_state: The comic state to update (modified in place).
        """
        changes = response.state_changes

        # Track the actual location ID (handles duplicate detection)
        actual_location_id = None

        # Add new location if the LLM introduced one
        if response.new_location:
            new_location_data = response.new_location
            location = DynamicLocation(
                id=new_location_data.get(
                    "id", f"loc_{comic_state.meta.panel_count}"
                ),
                name=new_location_data.get("name", "Unknown Location"),
                description=new_location_data.get("description", "")
            )
            # add_location returns the actual ID (existing if duplicate)
            actual_location_id = comic_state.world.add_location(location)

        # Add new character if the LLM introduced one
        if response.new_character:
            new_character_data = response.new_character
            character = DynamicCharacter(
                id=new_character_data.get(
                    "id", f"char_{comic_state.meta.panel_count}"
                ),
                name=new_character_data.get("name", "Unknown Character"),
                description=new_character_data.get("description", ""),
                current_location=comic_state.world.current_location_id
            )
            comic_state.world.add_character(character)

        # Update current location if it changed
        # Use actual_location_id if we detected a duplicate location
        if changes.get("current_location_id"):
            location_id = actual_location_id or changes["current_location_id"]
            comic_state.world.current_location_id = location_id

        if changes.get("current_location_name"):
            comic_state.world.current_location_name = changes["current_location_name"]

        # Update character locations based on who's present in the scene
        characters_present_ids = changes.get("characters_present_ids", [])
        for character_id in characters_present_ids:
            character = comic_state.world.get_character_by_id(character_id)
            if character:
                character.current_location = comic_state.world.current_location_id

        # Update the rolling narrative summary
        if response.rolling_summary_update:
            comic_state.narrative.rolling_summary = (
                response.rolling_summary_update
            )

        # Update render state from scene summary for visual generation
        scene_summary = response.scene_summary
        if scene_summary:
            comic_state.render = RenderState(
                scene_setting=scene_summary.get(
                    "scene_setting", comic_state.render.scene_setting
                ),
                characters_present=scene_summary.get(
                    "characters_present", comic_state.render.characters_present
                ),
                current_action=scene_summary.get(
                    "current_action", comic_state.render.current_action
                ),
            )

    def generate_opening_panel(self, comic_state: ComicState) -> NarratronResponse:
        """Generate the opening panel of the comic.

        Creates the first panel of the comic based on the blueprint's starting
        location and main character. This establishes the initial scene and sets
        the tone for the story.

        Args:
            comic_state: The current (initial) state of the comic.

        Returns:
            A NarratronResponse containing the opening panel narrative.

        Raises:
            ValueError: If the blueprint is not configured.
        """
        # TODO: The opening panel should be more grand! Maybe generate one classic opening panel and then generate the next ones at the same time?
        if not self.config.blueprint:
            raise ValueError("Cannot generate opening without blueprint")

        # Extract blueprint information
        blueprint = self.config.blueprint
        starting_location = blueprint.starting_location
        main_character = blueprint.main_character

        # Build compact system prompt (static info only)
        system_prompt = self._build_system_prompt()

        # Format the initial scene prompt with starting details
        user_message = load_prompt(
            _PROMPTS_DIR / "opening.user.md",
            starting_location=f"{starting_location.name}: {starting_location.description}",
            main_character=f"{main_character.name}: {main_character.description}",
        )

        # Prepare messages for the LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Get response from LLM and parse it
        response_text = self._call_llm(messages)  # Opening panel
        response = self._parse_response(response_text)

        # Log opening panel separately if logger available
        if self.logger:
            parsed_response = None
            try:
                parsed_response = json.loads(response_text)
            except json.JSONDecodeError:
                pass

            self.logger.log_opening_panel(
                system_prompt=system_prompt,
                user_message=user_message,
                response=response_text,
                parsed_response=parsed_response,
                model=LLM_MODEL,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS
            )

        # Apply state changes to initialize the comic state
        self._apply_state_changes(response, comic_state)

        return response
