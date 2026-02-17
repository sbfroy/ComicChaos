"""NARRATRON - The comic creation engine.

This module contains the Narratron AI engine that orchestrates comic creation.
The LLM has creative control over the story, dynamically introducing locations
and characters while maintaining consistency with the comic's blueprint and rules.
"""

import json
import os
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
from ..json_sanitizer import (
    sanitize_text,
    sanitize_json_string,
    sanitize_parsed_response,
    validate_json_response,
    safe_json_dumps,
    extract_json,
    repair_json,
)

from .models import (
    NarratronResponseSchema,
    OpeningSequenceSchema,
    FALLBACK_RESPONSE,
    NarratronResponse,
    TitleCardPanel,
    OpeningSequenceResponse,
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class Narratron:
    """The AI engine that orchestrates comic creation."""

    _NORWEGIAN_INSTRUCTION = (
        "\n\nLANGUAGE REQUIREMENT:"
        "\n- USER-FACING TEXT in Norwegian (Bokmål): All \"placeholder\" text and all "
        "\"text\" in auto-panels (pre-filled dialogue and narration) and \"title_treatment\" "
        "MUST be written in Norwegian (Bokmål)."
        "\n- INTERNAL FIELDS in English: scene_description, rolling_summary_update, "
        "short_term_narrative, long_term_narrative, and all scene_summary fields "
        "(scene_setting, characters_present, current_action) MUST remain in English. "
        "These feed into image generation and internal state — English keeps them consistent."
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
                extracted = extract_json(response_content)
                if extracted:
                    try:
                        parsed_response = json.loads(extracted)
                    except json.JSONDecodeError:
                        pass
                if parsed_response is None:
                    repaired = repair_json(response_content)
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
            extracted = extract_json(sanitized_text)
            if extracted:
                try:
                    data = json.loads(extracted)
                except json.JSONDecodeError:
                    pass

        # Strategy 3: Repair corrupted JSON
        if data is None:
            repaired = repair_json(sanitized_text)
            if repaired:
                try:
                    data = json.loads(repaired)
                    print("Successfully repaired corrupted LLM response.")
                except json.JSONDecodeError:
                    pass

        if data is None:
            return NarratronResponse(FALLBACK_RESPONSE)

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
            # Try to parse first — if valid JSON can be extracted, use it
            # even if there's trailing garbage. Only retry if parsing fails
            # entirely, to avoid discarding good narrative progress.
            response = self._parse_response(response_text)
            if response.raw is FALLBACK_RESPONSE:
                # Parsing failed completely — retry up to 2 times
                for attempt in range(2):
                    print(f"Unparseable LLM response, retry {attempt + 1}/2...")
                    response_text = self._call_llm(
                        messages, response_model=NarratronResponseSchema
                    )
                    response = self._parse_response(response_text)
                    if response.raw is not FALLBACK_RESPONSE:
                        break
        except Exception:
            response = NarratronResponse(FALLBACK_RESPONSE)

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
                    for repair_fn in (extract_json, repair_json):
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
                extracted = extract_json(sanitized_text)
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
                first_panel=NarratronResponse(FALLBACK_RESPONSE),
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
