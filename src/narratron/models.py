"""NARRATRON response models and schemas.

This module contains the data models used by the Narratron engine:
- Pydantic schemas for Structured Outputs (LLM response format)
- Response container classes for parsed LLM output
- Title card and opening sequence data structures

Classes:
    NarratronResponse: Structured response container from NARRATRON.
    TitleCardPanel: Title card panel data for the grand opening.
    OpeningSequenceResponse: Combined response for title card + first panel.
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Any

from pydantic import BaseModel


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


# --- Fallback response for unparseable LLM output ---

FALLBACK_RESPONSE = {
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


# --- Response container classes ---

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
