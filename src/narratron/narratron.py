"""NARRATRON - The comic creation engine.

The LLM has creative control over the story, dynamically introducing
locations and characters while maintaining world consistency.
"""

import json
import os
from typing import Any, Callable

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from ..state.game_state import GameState, RenderState, DynamicLocation, DynamicCharacter
from ..state.static_config import StaticConfig
from .prompts import NARRATRON_SYSTEM_PROMPT, INITIAL_SCENE_PROMPT


class NarratronResponse:
    """Structured response from NARRATRON."""

    def __init__(self, raw_response: dict):
        self.raw = raw_response

        # Input validation
        self.input_accepted = raw_response.get("input_accepted", True)
        self.rejection_reason = raw_response.get("rejection_reason", "")

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
    """The AI engine that creates comic panels.

    The LLM is the creative driver - it introduces new locations and characters
    as the story needs them, and validates user inputs against the world's logic.
    """

    def __init__(
        self,
        config: StaticConfig,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        verbose: bool = False
    ):
        self.config = config
        self.model = model
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.verbose = verbose
        self._console = Console() if verbose else None

    def _log(self, title: str, content: str, style: str = "dim", syntax: str | None = None) -> None:
        """Log verbose output if enabled."""
        if not self.verbose or not self._console:
            return

        if syntax:
            # Use syntax highlighting for JSON/code
            self._console.print(Panel(
                Syntax(content, syntax, theme="monokai", word_wrap=True),
                title=f"[bold]{title}[/bold]",
                border_style=style
            ))
        else:
            self._console.print(Panel(
                content,
                title=f"[bold]{title}[/bold]",
                border_style=style
            ))

    def _log_section(self, text: str, style: str = "yellow") -> None:
        """Log a section header."""
        if not self.verbose or not self._console:
            return
        self._console.print(f"\n[{style}]{'='*60}[/{style}]")
        self._console.print(f"[{style} bold]{text}[/{style} bold]")
        self._console.print(f"[{style}]{'='*60}[/{style}]\n")

    def _build_system_prompt(self, game_state: GameState) -> str:
        """Build the system prompt with current context."""
        world_context_parts = []

        if self.config.world_blueprint:
            bp = self.config.world_blueprint
            world_context_parts.append(f"COMIC TITLE: {bp.title}")
            world_context_parts.append(f"SETTING: {bp.setting}")
            world_context_parts.append(f"STORY CONCEPT: {bp.goal}")
            world_context_parts.append("")

            # Main character (from blueprint)
            world_context_parts.append("MAIN CHARACTER:")
            world_context_parts.append(
                f"  {game_state.world.main_character_name}: {game_state.world.main_character_description}"
            )
            world_context_parts.append("")

            # Known locations (dynamically created)
            world_context_parts.append("KNOWN LOCATIONS:")
            for loc in game_state.world.locations:
                world_context_parts.append(f"  - {loc.name} ({loc.id}): {loc.description[:100]}...")
            world_context_parts.append("")

            # Known characters (dynamically created)
            if game_state.world.characters:
                world_context_parts.append("CHARACTERS IN STORY:")
                for char in game_state.world.characters:
                    loc_info = f" [at: {char.current_location}]" if char.current_location else ""
                    world_context_parts.append(f"  - {char.name} ({char.id}): {char.description[:80]}...{loc_info}")
                world_context_parts.append("")

        world_context = "\n".join(world_context_parts)
        visual_style = self.config.world_blueprint.visual_style if self.config.world_blueprint else "comic book style"

        # Format world rules
        world_rules = "None specified - use common sense for this setting."
        if self.config.world_blueprint and self.config.world_blueprint.world_rules:
            world_rules = "\n".join(f"- {rule}" for rule in self.config.world_blueprint.world_rules)

        return NARRATRON_SYSTEM_PROMPT.format(
            visual_style=visual_style,
            world_rules=world_rules,
            world_context=f"CURRENT WORLD STATE:\n{world_context}"
        )

    def _call_llm(self, messages: list[dict]) -> str:
        """Make an API call to the LLM."""
        # Log the request
        if self.verbose:
            self._log_section("LLM API CALL", "magenta")
            self._log("System Prompt", messages[0]["content"], style="blue")
            self._log("User Message", messages[1]["content"], style="cyan")
            if self._console:
                self._console.print(f"[dim]Calling {self.model}...[/dim]\n")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
            max_tokens=1500,  # Increased for entity creation
            response_format={"type": "json_object"}
        )

        result = response.choices[0].message.content

        # Log the response
        if self.verbose:
            self._log_section("LLM RESPONSE", "green")
            # Pretty print the JSON response
            try:
                parsed = json.loads(result)
                pretty_json = json.dumps(parsed, indent=2)
                self._log("Raw JSON Response", pretty_json, style="green", syntax="json")
            except json.JSONDecodeError:
                self._log("Raw Response (not JSON)", result, style="red")

            # Log token usage if available
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                if self._console:
                    self._console.print(f"[dim]Tokens - Prompt: {usage.prompt_tokens}, Completion: {usage.completion_tokens}, Total: {usage.total_tokens}[/dim]\n")

        return result

    def _parse_response(self, response_text: str) -> NarratronResponse:
        """Parse the LLM response into a structured format."""
        try:
            data = json.loads(response_text)
            return NarratronResponse(data)
        except json.JSONDecodeError:
            return NarratronResponse({
                "input_accepted": True,
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

Create the next comic panel based on what the user wants to happen.
Remember: You have creative control. Reject requests that don't fit the world, introduce new characters/locations when needed."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        response_text = self._call_llm(messages)
        response = self._parse_response(response_text)

        # Apply state changes (including new entities)
        self._apply_state_changes(response, game_state)

        return response

    def _apply_state_changes(self, response: NarratronResponse, game_state: GameState) -> None:
        """Apply state changes from the response, including new entities."""
        changes = response.state_changes

        if self.verbose:
            self._log_section("APPLYING STATE CHANGES", "yellow")

        # Add new location if introduced
        if response.new_location:
            new_loc = response.new_location
            location = DynamicLocation(
                id=new_loc.get("id", f"loc_{game_state.meta.panel_count}"),
                name=new_loc.get("name", "Unknown Location"),
                description=new_loc.get("description", ""),
                visual_description=new_loc.get("visual_description", ""),
                first_appeared_panel=game_state.meta.panel_count + 1
            )
            game_state.world.add_location(location)
            if self.verbose and self._console:
                self._console.print(f"[green]+ New Location Added:[/green] {location.name} ({location.id})")
                self._console.print(f"  [dim]{location.description[:100]}...[/dim]")

        # Add new character if introduced
        if response.new_character:
            new_char = response.new_character
            character = DynamicCharacter(
                id=new_char.get("id", f"char_{game_state.meta.panel_count}"),
                name=new_char.get("name", "Unknown Character"),
                description=new_char.get("description", ""),
                current_location=game_state.world.current_location_id,
                first_appeared_panel=game_state.meta.panel_count + 1
            )
            game_state.world.add_character(character)
            if self.verbose and self._console:
                self._console.print(f"[green]+ New Character Added:[/green] {character.name} ({character.id})")
                self._console.print(f"  [dim]{character.description[:100]}...[/dim]")

        # Update current location
        if changes.get("current_location_id"):
            old_loc = game_state.world.current_location_id
            game_state.world.current_location_id = changes["current_location_id"]
            if self.verbose and self._console:
                self._console.print(f"[cyan]~ Location Changed:[/cyan] {old_loc} -> {changes['current_location_id']}")

        if changes.get("current_location_name"):
            game_state.world.current_location_name = changes["current_location_name"]

        # Update character locations based on who's present
        characters_present = changes.get("characters_present_ids", [])
        for char_id in characters_present:
            char = game_state.world.get_character_by_id(char_id)
            if char:
                char.current_location = game_state.world.current_location_id
                if self.verbose and self._console:
                    self._console.print(f"[cyan]~ Character Moved:[/cyan] {char.name} -> {game_state.world.current_location_id}")

        # Set flags
        for flag, value in changes.get("flags_set", {}).items():
            game_state.world.flags[flag] = value
            if self.verbose and self._console:
                self._console.print(f"[cyan]~ Flag Set:[/cyan] {flag} = {value}")

        # Update narrative
        if response.rolling_summary_update:
            game_state.narrative.rolling_summary = response.rolling_summary_update
            if self.verbose and self._console:
                self._console.print(f"[cyan]~ Story Summary Updated[/cyan]")

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
            if self.verbose and self._console:
                self._console.print(f"[cyan]~ Render State Updated:[/cyan] mood={vs.get('mood')}, time={vs.get('time_of_day')}")

        if self.verbose and self._console:
            self._console.print()  # Add spacing

    def generate_opening_panel(self, game_state: GameState) -> NarratronResponse:
        """Generate the opening panel of the comic."""
        if not self.config.world_blueprint:
            raise ValueError("Cannot generate opening without world blueprint")

        bp = self.config.world_blueprint
        starting_loc = bp.starting_location
        main_char = bp.main_character

        system_prompt = self._build_system_prompt(game_state)

        user_message = INITIAL_SCENE_PROMPT.format(
            starting_location=f"{starting_loc.name}: {starting_loc.description}",
            main_character=f"{main_char.name}: {main_char.description}",
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
