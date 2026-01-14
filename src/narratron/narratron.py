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

from ..config import LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
from ..state.comic_state import (
    ComicState,
    RenderState,
    DynamicLocation,
    DynamicCharacter,
)
from ..state.static_config import StaticConfig
from .prompts import NARRATRON_SYSTEM_PROMPT, INITIAL_SCENE_PROMPT

class NarratronResponse:
    """Structured response from NARRATRON.
    
    This class encapsulates all data returned by the NARRATRON AI engine,
    including narrative content, new entities, and state changes.
    
    Attributes:
        raw: The raw dictionary response from the LLM.
        panel_narrative: The narrative text for the comic panel.
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

        # Core narrative elements
        self.panel_narrative: str = raw_response.get("panel_narrative", "")

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
    ) -> None:
        """Initialize the Narratron engine.
        
        Args:
            config: Static configuration containing blueprint and rules.
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY environment variable.
        """
        self.config: StaticConfig = config
        self.client: OpenAI = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )

    def _build_system_prompt(self, comic_state: ComicState) -> str:
        """Build the system prompt with current comic context.
        
        Constructs a comprehensive system prompt that includes the comic's blueprint,
        visual style, rules, and current state (known locations, characters, etc.).
        This gives the LLM full context to make informed creative decisions.
        
        Args:
            comic_state: The current state of the comic including world and narrative.
        
        Returns:
            The formatted system prompt string ready for the LLM.
        """
        # Build context string part by part for clarity
        comic_context_parts: List[str] = []
        blueprint = self.config.blueprint

        # Add comic title and synopsis
        comic_context_parts.append(f"COMIC TITLE: {blueprint.title}")
        comic_context_parts.append(f"SYNOPSIS: {blueprint.synopsis}")
        comic_context_parts.append("")  # Blank line for readability

        # Add main character information (from blueprint)
        comic_context_parts.append("MAIN CHARACTER:")
        comic_context_parts.append(
            f"  {comic_state.world.main_character_name}: "
            f"{comic_state.world.main_character_description}"
        )
        comic_context_parts.append("")

        # Add all known locations (dynamically created during the story)
        comic_context_parts.append("KNOWN LOCATIONS:")
        for location in comic_state.world.locations:
            comic_context_parts.append(
                f"  - {location.name} ({location.id}): {location.description}"
            )
        comic_context_parts.append("")

        # Add all known characters (dynamically created during the story)
        if comic_state.world.characters:
            comic_context_parts.append("CHARACTERS IN STORY:")
            for character in comic_state.world.characters:
                # Include current location if available
                location_info = (
                    f" [at: {character.current_location}]"
                    if character.current_location
                    else ""
                )
                comic_context_parts.append(
                    f"  - {character.name} ({character.id}): "
                    f"{character.description}{location_info}"
                )
            comic_context_parts.append("")

        # Join all context parts into a single string
        comic_context = "\n".join(comic_context_parts)

        # Extract visual style and rules from blueprint
        visual_style = self.config.blueprint.visual_style
        rules = "\n".join(f"- {rule}" for rule in self.config.blueprint.rules)

        # Format and return the complete system prompt
        return NARRATRON_SYSTEM_PROMPT.format(
            visual_style=visual_style,
            rules=rules,
            comic_context=f"CURRENT COMIC STATE:\n{comic_context}",
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

        return response.choices[0].message.content

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
            return NarratronResponse(
                {
                    "panel_narrative": "Something unexpected happened...",
                    "state_changes": {},
                    "visual_summary": {},
                }
            )

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
        # Build the system prompt with current context
        system_prompt = self._build_system_prompt(comic_state)
        context = comic_state.get_context_summary()

        # Construct the user message with current state and user's request
        user_message = f"""CURRENT STORY STATE:
{context}

USER WANTS: {user_input}

Create the next comic panel based on what the user wants to happen.
Remember: Say YES to creative ideas! Introduce new characters/locations when needed."""

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
            comic_state.world.add_location(location)

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
        if changes.get("current_location_id"):
            comic_state.world.current_location_id = changes["current_location_id"]

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
        if not self.config.blueprint:
            raise ValueError("Cannot generate opening without blueprint")

        # Extract blueprint information
        blueprint = self.config.blueprint
        starting_location = blueprint.starting_location
        main_character = blueprint.main_character

        # Build system prompt with current context
        system_prompt = self._build_system_prompt(comic_state)

        # Format the initial scene prompt with starting details
        user_message = INITIAL_SCENE_PROMPT.format(
            starting_location=(
                f"{starting_location.name}: {starting_location.description}"
            ),
            main_character=f"{main_character.name}: {main_character.description}",
        )

        # Prepare messages for the LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Get response from LLM and parse it
        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes to initialize the comic state
        self._apply_state_changes(response, comic_state)

        return response
