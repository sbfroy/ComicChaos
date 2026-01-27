"""NARRATRON - The comic creation engine.

This module contains the Narratron AI engine that orchestrates comic creation.
The LLM has creative control over the story, dynamically introducing locations
and characters while maintaining consistency with the comic's blueprint and rules.

Classes:
    NarratronResponse: Structured response container from NARRATRON.
    TitleCardPanel: Title card panel data for the grand opening.
    OpeningSequenceResponse: Combined response for title card + first panel.
    Narratron: The AI engine that orchestrates comic creation.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from openai import OpenAI

from pathlib import Path

from ..config import LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS
from ..state.comic_state import (
    ComicState,
    RenderState,
)
from ..state.static_config import StaticConfig
from ..logging.interaction_logger import InteractionLogger
from ..prompt_loader import load_prompt, load_json

_DIR = Path(__file__).parent
_PROMPTS_DIR = _DIR.parent / "prompts"

class NarratronResponse:
    """Structured response from NARRATRON.

    Attributes:
        raw: The raw dictionary response from the LLM.
        scene_description: Visual description of what's happening (for image generation).
        elements: List of panel elements (speech bubbles, etc.) - most pre-filled, one for user input.
        state_changes: Dictionary of changes to apply to the comic state.
        scene_summary: Summary of the current scene for rendering.
        rolling_summary_update: Updated summary of the story so far.
    """

    def __init__(self, raw_response: Dict[str, Any]) -> None:
        self.raw: Dict[str, Any] = raw_response
        self.scene_description: str = raw_response.get("scene_description", "")
        self.elements: List[Dict[str, Any]] = raw_response.get("elements", [])
        self.state_changes: Dict[str, Any] = raw_response.get("state_changes", {})
        self.scene_summary: Dict[str, Any] = raw_response.get("scene_summary", {})
        self.rolling_summary_update: str = raw_response.get("rolling_summary_update", "")


@dataclass
class TitleCardPanel:
    """Title card panel data - visual intro with no user interaction."""

    scene_description: str
    title_treatment: str
    atmosphere: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TitleCardPanel":
        return cls(
            scene_description=data.get("scene_description", ""),
            title_treatment=data.get("title_treatment", ""),
            atmosphere=data.get("atmosphere", ""),
        )


@dataclass
class OpeningSequenceResponse:
    """Combined response for grand opening sequence."""

    title_card: TitleCardPanel
    first_panel: NarratronResponse

    @classmethod
    def from_raw(cls, raw_response: Dict[str, Any]) -> "OpeningSequenceResponse":
        title_card_data = raw_response.get("title_card", {})
        first_panel_data = raw_response.get("first_panel", {})
        return cls(
            title_card=TitleCardPanel.from_dict(title_card_data),
            first_panel=NarratronResponse(first_panel_data),
        )


class Narratron:
    """The AI engine that orchestrates comic creation."""

    def __init__(
        self,
        config: StaticConfig,
        api_key: Optional[str] = None,
        logger: Optional[InteractionLogger] = None,
    ) -> None:
        self.config: StaticConfig = config
        self.client: OpenAI = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )
        self.logger: Optional[InteractionLogger] = logger

    def _build_system_prompt(self) -> str:
        """Build the system prompt with static comic information only."""
        blueprint = self.config.blueprint
        rules = " | ".join(self.config.blueprint.rules) if self.config.blueprint.rules else "None"

        return load_prompt(
            _PROMPTS_DIR / "narratron.system.md",
            title=blueprint.title,
            visual_style=blueprint.visual_style,
            rules=rules,
        )

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Make an API call to the LLM."""
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )

        response_content = response.choices[0].message.content

        if self.logger:
            system_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_message = next((m["content"] for m in messages if m["role"] == "user"), "")

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
        """Parse the LLM response into a structured format."""
        try:
            data = json.loads(response_text)
            return NarratronResponse(data)
        except json.JSONDecodeError:
            fallback_data = load_json(_DIR / "error_fallback.json")
            return NarratronResponse(fallback_data)

    def process_input(
        self, user_input: str, comic_state: ComicState
    ) -> NarratronResponse:
        """Process user input and create the next comic panel."""
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(user_input, comic_state)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        self._apply_state_changes(response, comic_state)

        return response

    def _build_user_message(self, user_input: str, comic_state: ComicState) -> str:
        """Build compact user message with all dynamic context."""
        main_char = f"{comic_state.main_character_name}: {comic_state.main_character_description}"

        # Recent panels (compact)
        recent_panels = ""
        if comic_state.narrative.panels:
            panel_lines = []
            for panel in comic_state.get_recent_panels(3):
                narrative = panel.narrative[:150] + "..." if len(panel.narrative) > 150 else panel.narrative
                panel_lines.append(f"P{panel.panel_number}: {narrative}")
            recent_panels = "RECENT:\n" + "\n".join(panel_lines)

        return load_prompt(
            _PROMPTS_DIR / "panel.user.md",
            main_character=main_char,
            rolling_summary=comic_state.narrative.rolling_summary,
            recent_panels=recent_panels,
            user_input=user_input,
        )

    def _apply_state_changes(
        self, response: NarratronResponse, comic_state: ComicState
    ) -> None:
        """Apply state changes from the response."""
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
        """Generate the opening panel of the comic."""
        if not self.config.blueprint:
            raise ValueError("Cannot generate opening without blueprint")

        blueprint = self.config.blueprint
        starting_location = blueprint.starting_location
        main_character = blueprint.main_character

        system_prompt = self._build_system_prompt()

        user_message = load_prompt(
            _PROMPTS_DIR / "opening.user.md",
            starting_location=f"{starting_location.name}: {starting_location.description}",
            main_character=f"{main_character.name}: {main_character.description}",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

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

        self._apply_state_changes(response, comic_state)

        return response

    def generate_opening_sequence(
        self, comic_state: ComicState
    ) -> OpeningSequenceResponse:
        """Generate the grand opening sequence: title card + first interactive panel."""
        if not self.config.blueprint:
            raise ValueError("Cannot generate opening without blueprint")

        blueprint = self.config.blueprint

        system_prompt = self._build_system_prompt()

        user_message = load_prompt(
            _PROMPTS_DIR / "opening_sequence.user.md",
            title=blueprint.title,
            synopsis=blueprint.synopsis,
            visual_style=blueprint.visual_style,
            starting_location=f"{blueprint.starting_location.name}: {blueprint.starting_location.description}",
            main_character=f"{blueprint.main_character.name}: {blueprint.main_character.description}",
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response_text = self._call_llm(messages)

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
                max_tokens=LLM_MAX_TOKENS,
            )

        try:
            data = json.loads(response_text)
            response = OpeningSequenceResponse.from_raw(data)
        except json.JSONDecodeError:
            fallback_data = load_json(_DIR / "error_fallback.json")
            response = OpeningSequenceResponse(
                title_card=TitleCardPanel(
                    scene_description=f"A dramatic establishing shot for {blueprint.title}",
                    title_treatment=blueprint.title,
                    atmosphere=blueprint.synopsis,
                ),
                first_panel=NarratronResponse(fallback_data),
            )

        self._apply_state_changes(response.first_panel, comic_state)

        return response
