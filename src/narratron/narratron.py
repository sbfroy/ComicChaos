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

from ..state.comic_state import (
    ComicState,
    RenderState,
)
from ..state.static_config import StaticConfig
from ..logging.interaction_logger import InteractionLogger
from ..prompt_loader import load_prompt

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_FALLBACK_RESPONSE = {
    "panels": [
        {
            "scene_description": "Something unexpected happened...",
            "elements": [
                {
                    "type": "narration",
                    "position": "bottom-center",
                    "user_input": True,
                    "placeholder": "What happens next?",
                }
            ],
        }
    ],
    "scene_summary": {},
    "short_term_narrative": [],
    "long_term_narrative": [],
    "reached_outcome": None,
}


@dataclass
class PanelData:
    """Data for a single panel in a Narratron response."""

    scene_description: str
    elements: List[Dict[str, Any]]
    is_auto: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PanelData":
        elements = data.get("elements", [])
        is_auto = all(not el.get("user_input", False) for el in elements)
        return cls(
            scene_description=data.get("scene_description", ""),
            elements=elements,
            is_auto=is_auto,
        )


class NarratronResponse:
    """Structured response from NARRATRON."""

    def __init__(self, raw_response: Dict[str, Any]) -> None:
        self.raw: Dict[str, Any] = raw_response

        # Support both panels array and legacy single-panel format
        panels_data = raw_response.get("panels", None)
        if panels_data and isinstance(panels_data, list):
            self.panels: List[PanelData] = [PanelData.from_dict(p) for p in panels_data]
        else:
            # Legacy single-panel format: wrap in a list
            self.panels = [PanelData(
                scene_description=raw_response.get("scene_description", ""),
                elements=raw_response.get("elements", []),
                is_auto=False,
            )]

        # Enforce: last panel must be interactive
        if self.panels and self.panels[-1].is_auto:
            last = self.panels[-1]
            if last.elements:
                last.elements[-1]["user_input"] = True
                last.elements[-1].pop("text", None)
                last.elements[-1].setdefault("placeholder", "What happens next?")
            last.is_auto = False

        # Enforce max 2 panels
        if len(self.panels) > 2:
            # Keep only the last auto panel (if any) + the last interactive panel
            auto_panels = [p for p in self.panels if p.is_auto]
            interactive_panels = [p for p in self.panels if not p.is_auto]
            if auto_panels and interactive_panels:
                self.panels = [auto_panels[-1], interactive_panels[-1]]
            elif interactive_panels:
                self.panels = [interactive_panels[-1]]
            else:
                self.panels = [self.panels[-1]]

        # Backward compat: expose last panel's data
        self.scene_description: str = self.panels[-1].scene_description if self.panels else ""
        self.elements: List[Dict[str, Any]] = self.panels[-1].elements if self.panels else []

        # Top-level fields
        self.scene_summary: Dict[str, Any] = raw_response.get("scene_summary", {})
        self.rolling_summary_update: str = raw_response.get("rolling_summary_update", "")
        self.short_term_narrative: List[str] = raw_response.get("short_term_narrative", [])
        self.long_term_narrative: List[str] = raw_response.get("long_term_narrative", [])
        self.reached_outcome: Optional[str] = raw_response.get("reached_outcome", None)


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
    initial_narrative: Dict[str, List[str]]

    @classmethod
    def from_raw(cls, raw_response: Dict[str, Any]) -> "OpeningSequenceResponse":
        title_card_data = raw_response.get("title_card", {})
        first_panel_data = raw_response.get("first_panel", {})
        initial_narrative = raw_response.get("initial_narrative", {"short_term": [], "long_term": []})
        return cls(
            title_card=TitleCardPanel.from_dict(title_card_data),
            first_panel=NarratronResponse(first_panel_data),
            initial_narrative=initial_narrative,
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
        """Make an API call to the LLM.

        Raises on API errors so callers can fall back gracefully.
        """
        cc = self.config.comic_config
        response = self.client.chat.completions.create(
            model=cc.llm_model,
            messages=messages,
            temperature=cc.llm_temperature,
            top_p=cc.llm_top_p,
            max_tokens=cc.llm_max_tokens,
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
                model=cc.llm_model,
                temperature=cc.llm_temperature,
                max_tokens=cc.llm_max_tokens
            )

        return response_content

    def _parse_response(self, response_text: str) -> NarratronResponse:
        """Parse the LLM response into a structured format."""
        try:
            data = json.loads(response_text)
            return NarratronResponse(data)
        except json.JSONDecodeError:
            return NarratronResponse(_FALLBACK_RESPONSE)

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

        try:
            response_text = self._call_llm(messages)
            response = self._parse_response(response_text)
        except Exception:
            response = NarratronResponse(_FALLBACK_RESPONSE)

        self._apply_state_changes(response, comic_state)

        return response

    def _build_user_message(self, user_input: str, comic_state: ComicState) -> str:
        """Build compact user message with all dynamic context."""
        main_char = f"{comic_state.main_character_name}: {comic_state.main_character_description}"

        # All blueprint characters (so the LLM never forgets species/descriptions)
        all_characters = ""
        if self.config.blueprint.characters and len(self.config.blueprint.characters) > 1:
            char_lines = [
                f"- {c.name}: {c.description}"
                for c in self.config.blueprint.characters[1:]  # Skip main char (already above)
            ]
            all_characters = "OTHER CHARACTERS:\n" + "\n".join(char_lines)

        # Recent panels (compact)
        recent_panels = ""
        if comic_state.narrative.panels:
            panel_lines = []
            for panel in comic_state.get_recent_panels(3):
                narrative = panel.narrative[:150] + "..." if len(panel.narrative) > 150 else panel.narrative
                panel_lines.append(f"P{panel.panel_number}: {narrative}")
            recent_panels = "RECENT:\n" + "\n".join(panel_lines)

        # Format story narrative direction
        story_narrative = ""
        direction = comic_state.narrative.direction
        if direction.short_term or direction.long_term:
            narrative_parts = []
            if direction.short_term:
                narrative_parts.append("SHORT-TERM: " + "; ".join(direction.short_term))
            if direction.long_term:
                narrative_parts.append("LONG-TERM: " + "; ".join(direction.long_term))
            story_narrative = "STORY NARRATIVE:\n" + "\n".join(narrative_parts)

        # Format final outcomes (if defined in blueprint)
        final_outcomes = ""
        if self.config.blueprint.final_outcomes:
            outcomes_str = "\n".join(f"  - {o}" for o in self.config.blueprint.final_outcomes)
            final_outcomes = f"POSSIBLE ENDINGS:\n{outcomes_str}"

        return load_prompt(
            _PROMPTS_DIR / "panel.user.md",
            main_character=main_char,
            all_characters=all_characters,
            rolling_summary=comic_state.narrative.rolling_summary,
            story_narrative=story_narrative,
            final_outcomes=final_outcomes,
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

        # Update story narrative direction
        if isinstance(response.short_term_narrative, list) and response.short_term_narrative:
            comic_state.narrative.direction.short_term = response.short_term_narrative
        if isinstance(response.long_term_narrative, list) and response.long_term_narrative:
            comic_state.narrative.direction.long_term = response.long_term_narrative

        # Check for reached outcome
        if response.reached_outcome:
            comic_state.reached_outcome = response.reached_outcome

    def generate_opening_sequence(
        self, comic_state: ComicState
    ) -> OpeningSequenceResponse:
        """Generate the grand opening sequence: title card + first interactive panel."""
        if not self.config.blueprint:
            raise ValueError("Cannot generate opening without blueprint")

        blueprint = self.config.blueprint

        system_prompt = self._build_system_prompt()

        long_term_narrative_section = ""
        if blueprint.long_term_narrative:
            narrative_str = "; ".join(blueprint.long_term_narrative)
            long_term_narrative_section = f"LONG-TERM NARRATIVE (use these as-is for initial_narrative.long_term): {narrative_str}"

        final_outcomes_section = ""
        if blueprint.final_outcomes:
            outcomes_str = "\n".join(f"  - {o}" for o in blueprint.final_outcomes)
            final_outcomes_section = f"POSSIBLE ENDINGS (these are the only ways the story can end):\n{outcomes_str}"

        user_message = load_prompt(
            _PROMPTS_DIR / "opening_sequence.user.md",
            title=blueprint.title,
            synopsis=blueprint.synopsis,
            visual_style=blueprint.visual_style,
            starting_location=f"{blueprint.starting_location.name}: {blueprint.starting_location.description}",
            main_character=f"{blueprint.main_character.name}: {blueprint.main_character.description}",
            long_term_narrative_section=long_term_narrative_section,
            final_outcomes_section=final_outcomes_section,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
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
                    model=self.config.comic_config.llm_model,
                    temperature=self.config.comic_config.llm_temperature,
                    max_tokens=self.config.comic_config.llm_max_tokens,
                )

            data = json.loads(response_text)
            response = OpeningSequenceResponse.from_raw(data)
        except Exception:
            response = OpeningSequenceResponse(
                title_card=TitleCardPanel(
                    scene_description=f"A dramatic establishing shot for {blueprint.title}",
                    title_treatment=blueprint.title,
                    atmosphere=blueprint.synopsis,
                ),
                first_panel=NarratronResponse(_FALLBACK_RESPONSE),
                initial_narrative={"short_term": [], "long_term": []},
            )

        self._apply_state_changes(response.first_panel, comic_state)

        # Apply initial story narrative
        if response.initial_narrative:
            st = response.initial_narrative.get("short_term", [])
            if isinstance(st, list) and st:
                comic_state.narrative.direction.short_term = st
            # Only use LLM's long-term narrative if the blueprint didn't define any
            if not self.config.blueprint.long_term_narrative:
                lt = response.initial_narrative.get("long_term", [])
                if isinstance(lt, list) and lt:
                    comic_state.narrative.direction.long_term = lt

        return response
