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
import re
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from openai import OpenAI
from pydantic import BaseModel

from pathlib import Path

from ..state.comic_state import (
    ComicState,
    RenderState,
)
from ..state.static_config import StaticConfig
from ..logging.interaction_logger import InteractionLogger
from ..prompt_loader import load_prompt
from ..json_sanitizer import (
    sanitize_text,
    sanitize_json_string,
    sanitize_parsed_response,
    validate_json_response,
    safe_json_dumps,
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


# --- Pydantic schemas for Structured Outputs ---

class ElementSchema(BaseModel):
    type: str
    character_name: Optional[str] = None
    position: str
    user_input: bool
    placeholder: Optional[str] = None
    text: Optional[str] = None


class PanelSchema(BaseModel):
    scene_description: str
    elements: list[ElementSchema]


class SceneSummarySchema(BaseModel):
    scene_setting: str
    characters_present: list[str]
    current_action: str


class NarratronResponseSchema(BaseModel):
    panels: list[PanelSchema]
    scene_summary: SceneSummarySchema
    rolling_summary_update: str
    short_term_narrative: list[str]
    long_term_narrative: list[str]


class TitleCardSchema(BaseModel):
    scene_description: str
    title_treatment: str
    atmosphere: str


class InitialNarrativeSchema(BaseModel):
    short_term: list[str]
    long_term: list[str]


class OpeningSequenceSchema(BaseModel):
    title_card: TitleCardSchema
    first_panel: NarratronResponseSchema
    initial_narrative: InitialNarrativeSchema


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

    _NORWEGIAN_INSTRUCTION = (
        "\n\nLANGUAGE REQUIREMENT: ALL text output — including scene_description, "
        "all element text, placeholder text, rolling_summary_update, short_term_narrative, "
        "and long_term_narrative — MUST be written in Norwegian (Bokmål). "
        "This applies to dialogue, narration, placeholders, and all story content. "
        "Only the JSON keys remain in English."
        "\n\nENCODING REQUIREMENT: Write Norwegian characters (æ, ø, å, Æ, Ø, Å) and "
        "all other special characters (€, é, ü, etc.) as literal UTF-8 characters "
        "directly in the JSON string values. Do NOT use Unicode escape sequences like "
        "\\u00e6 — write the actual character æ instead. Never output null bytes (\\u0000), "
        "raw hexadecimal byte sequences, or incomplete escape sequences."
    )

    def __init__(
        self,
        config: StaticConfig,
        api_key: Optional[str] = None,
        logger: Optional[InteractionLogger] = None,
        language: str = "no",
    ) -> None:
        self.config: StaticConfig = config
        self.client: OpenAI = OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY")
        )
        self.logger: Optional[InteractionLogger] = logger
        self.language: str = language

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

    def _call_llm(
        self,
        messages: List[Dict[str, str]],
        response_model: Optional[type] = None,
    ) -> str:
        """Make an API call to the LLM.

        When *response_model* is a Pydantic class the call uses Structured
        Outputs (``client.beta.chat.completions.parse``) so the response is
        guaranteed to match the schema.  If the structured call fails for any
        reason (unsupported model, API change, etc.) it falls back to the
        legacy ``json_object`` mode automatically.

        Returns the raw response text in both paths so downstream parsing
        logic works unchanged.
        """
        cc = self.config.comic_config

        response_content: str
        parsed_via_schema = False

        # --- Structured Outputs path ---
        if response_model is not None:
            try:
                response = self.client.beta.chat.completions.parse(
                    model=cc.llm_model,
                    messages=messages,
                    temperature=cc.llm_temperature,
                    top_p=cc.llm_top_p,
                    max_tokens=cc.llm_max_tokens,
                    response_format=response_model,
                )
                parsed = response.choices[0].message.parsed
                if parsed is not None:
                    response_content = safe_json_dumps(parsed.model_dump())
                    parsed_via_schema = True
                else:
                    # Model refused or returned None — fall through to legacy
                    response_content = response.choices[0].message.content or ""
            except Exception:
                # Structured outputs not supported or failed — fall through
                response_model = None  # signal to use legacy path below

        # --- Legacy json_object path ---
        if not parsed_via_schema:
            response = self.client.chat.completions.create(
                model=cc.llm_model,
                messages=messages,
                temperature=cc.llm_temperature,
                top_p=cc.llm_top_p,
                max_tokens=cc.llm_max_tokens,
                response_format={"type": "json_object"},
            )
            response_content = response.choices[0].message.content

        # --- Logging (same for both paths) ---
        if self.logger:
            system_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_message = next((m["content"] for m in messages if m["role"] == "user"), "")

            parsed_response = None
            try:
                parsed_response = json.loads(response_content)
            except json.JSONDecodeError:
                # Try extraction and repair so the log captures the data
                extracted = self._extract_json(response_content)
                if extracted:
                    try:
                        parsed_response = json.loads(extracted)
                    except json.JSONDecodeError:
                        pass
                if parsed_response is None:
                    repaired = self._repair_json(response_content)
                    if repaired:
                        try:
                            parsed_response = json.loads(repaired)
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

    @staticmethod
    def _is_corrupted_response(text: str) -> bool:
        """Check if the LLM response text shows signs of corruption.

        Detects object replacement characters, excessive repeated characters,
        and responses that end with non-JSON garbage after the closing brace.
        """
        if "\ufffc" in text:
            return True
        # Check for trailing garbage after the last closing brace
        last_brace = text.rfind("}")
        if last_brace >= 0:
            trailing = text[last_brace + 1:].strip()
            if len(trailing) > 10:
                return True
        # Check for abnormally long runs of repeated characters
        if re.search(r"(.)\1{50,}", text):
            return True
        return False

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Try to extract valid JSON from text that may contain trailing garbage."""
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidate = text[first_brace:last_brace + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _repair_json(text: str) -> Optional[str]:
        """Attempt to repair corrupted JSON from LLM responses.

        Handles a known gpt-4.1 failure mode where the model outputs valid JSON
        for all fields, then appends a trailing comma and an unterminated string
        before the closing brace, followed by repetitive garbage. The corruption
        always occurs after the last complete JSON value (typically the
        long_term_narrative array).

        Strategy:
        1. Find the outermost opening brace.
        2. Walk the string with a brace/bracket depth counter, respecting
           JSON string escaping, to locate the position just after the last
           successfully closed array or object at depth 1 (i.e. a top-level
           value boundary).
        3. Truncate there, strip any trailing comma, and close the object.
        """
        start = text.find("{")
        if start < 0:
            return None

        # Walk through the JSON tracking depth and string state
        in_string = False
        escape_next = False
        depth = 0
        last_value_end = -1  # position after the last ]/} that returns to depth 1

        for i in range(start, len(text)):
            ch = text[i]

            if escape_next:
                escape_next = False
                continue

            if in_string:
                if ch == "\\":
                    escape_next = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 1:
                    # Just closed a top-level value — record this position
                    last_value_end = i + 1
                elif depth == 0:
                    # Properly closed outer object — try parsing as-is
                    candidate = text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break

        # If we tracked a valid value boundary, truncate and close
        if last_value_end > start:
            truncated = text[start:last_value_end].rstrip()
            # Strip any trailing commas left after truncation
            truncated = truncated.rstrip(",").rstrip()
            truncated += "\n}"
            try:
                json.loads(truncated)
                return truncated
            except json.JSONDecodeError:
                pass

        return None

    def _parse_response(self, response_text: str) -> NarratronResponse:
        """Parse the LLM response into a structured format.

        Applies encoding sanitization before parsing, then validates
        the parsed result for encoding integrity. Tries three parse
        strategies in order:
        1. Direct JSON parse
        2. Extract JSON between first { and last }
        3. Repair corrupted JSON by truncating at the last valid value boundary

        After successful parsing, all string values are sanitized to
        remove null bytes, invisible characters, and malformed Unicode.
        """
        # Pre-sanitize the raw JSON string to fix encoding issues
        sanitized_text = sanitize_json_string(response_text)

        # Strategy 1: Direct parse
        data = None
        try:
            data = json.loads(sanitized_text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract between first { and last }
        if data is None:
            extracted = self._extract_json(sanitized_text)
            if extracted:
                try:
                    data = json.loads(extracted)
                except json.JSONDecodeError:
                    pass

        # Strategy 3: Repair corrupted JSON
        if data is None:
            repaired = self._repair_json(sanitized_text)
            if repaired:
                try:
                    data = json.loads(repaired)
                    print("Successfully repaired corrupted LLM response.")
                except json.JSONDecodeError:
                    pass

        if data is None:
            return NarratronResponse(_FALLBACK_RESPONSE)

        # Deep-sanitize all string values in the parsed response
        data = sanitize_parsed_response(data)

        # Validate encoding integrity and log warnings
        warnings = validate_json_response(data, "NarratronResponse")
        if warnings:
            print(f"JSON encoding warnings after sanitization: {warnings}")

        return NarratronResponse(data)

    def _localize_fallback_placeholders(self, response: NarratronResponse) -> None:
        """Replace English fallback placeholders with localized versions."""
        if self.language != "no":
            return
        for panel in response.panels:
            for el in panel.elements:
                if el.get("placeholder") == "What happens next?":
                    el["placeholder"] = "Hva skjer videre?"

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
            response_text = self._call_llm(
                messages, response_model=NarratronResponseSchema
            )
            # Retry up to 2 times if the response looks corrupted
            for attempt in range(2):
                if not self._is_corrupted_response(response_text):
                    break
                print(f"Corrupted LLM response detected, retry {attempt + 1}/2...")
                response_text = self._call_llm(
                    messages, response_model=NarratronResponseSchema
                )
            response = self._parse_response(response_text)
        except Exception:
            response = NarratronResponse(_FALLBACK_RESPONSE)

        self._localize_fallback_placeholders(response)
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

        # Format narrative premise (if defined in blueprint)
        narrative_premise = ""
        if self.config.blueprint.narrative_premise:
            narrative_premise = self.config.blueprint.narrative_premise

        message = load_prompt(
            _PROMPTS_DIR / "panel.user.md",
            main_character=main_char,
            all_characters=all_characters,
            rolling_summary=comic_state.narrative.rolling_summary,
            story_narrative=story_narrative,
            narrative_premise=narrative_premise,
            recent_panels=recent_panels,
            user_input=user_input,
        )

        if self.language == "no":
            message += self._NORWEGIAN_INSTRUCTION

        return message

    def _apply_state_changes(
        self, response: NarratronResponse, comic_state: ComicState
    ) -> None:
        """Apply state changes from the response.

        All text values are sanitized before storing in state to prevent
        encoding corruption from propagating into subsequent LLM prompts.
        """
        # Update the rolling narrative summary
        if response.rolling_summary_update:
            comic_state.narrative.rolling_summary = sanitize_text(
                response.rolling_summary_update
            )

        # Update render state from scene summary for visual generation
        scene_summary = response.scene_summary
        if scene_summary:
            comic_state.render = RenderState(
                scene_setting=sanitize_text(scene_summary.get(
                    "scene_setting", comic_state.render.scene_setting
                )),
                characters_present=[
                    sanitize_text(c) for c in scene_summary.get(
                        "characters_present", comic_state.render.characters_present
                    )
                ],
                current_action=sanitize_text(scene_summary.get(
                    "current_action", comic_state.render.current_action
                )),
            )

        # Update story narrative direction
        if isinstance(response.short_term_narrative, list) and response.short_term_narrative:
            comic_state.narrative.direction.short_term = [
                sanitize_text(s) for s in response.short_term_narrative
            ]
        if isinstance(response.long_term_narrative, list) and response.long_term_narrative:
            comic_state.narrative.direction.long_term = [
                sanitize_text(s) for s in response.long_term_narrative
            ]

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

        narrative_premise_section = ""
        if blueprint.narrative_premise:
            narrative_premise_section = f"NARRATIVE PREMISE: {blueprint.narrative_premise}"

        user_message = load_prompt(
            _PROMPTS_DIR / "opening_sequence.user.md",
            title=blueprint.title,
            synopsis=blueprint.synopsis,
            visual_style=blueprint.visual_style,
            starting_location=f"{blueprint.starting_location.name}: {blueprint.starting_location.description}",
            main_character=f"{blueprint.main_character.name}: {blueprint.main_character.description}",
            long_term_narrative_section=long_term_narrative_section,
            narrative_premise_section=narrative_premise_section,
        )

        if self.language == "no":
            user_message += self._NORWEGIAN_INSTRUCTION

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            response_text = self._call_llm(
                messages, response_model=OpeningSequenceSchema
            )

            if self.logger:
                parsed_response = None
                try:
                    parsed_response = json.loads(response_text)
                except json.JSONDecodeError:
                    for repair_fn in (self._extract_json, self._repair_json):
                        repaired = repair_fn(response_text)
                        if repaired:
                            try:
                                parsed_response = json.loads(repaired)
                                break
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

            # Pre-sanitize the raw JSON, then parse
            sanitized_text = sanitize_json_string(response_text)
            try:
                data = json.loads(sanitized_text)
            except json.JSONDecodeError:
                extracted = self._extract_json(sanitized_text)
                if extracted:
                    data = json.loads(extracted)
                else:
                    raise
            # Deep-sanitize all string values
            data = sanitize_parsed_response(data)
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

        self._localize_fallback_placeholders(response.first_panel)

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
