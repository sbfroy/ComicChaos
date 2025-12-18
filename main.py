#!/usr/bin/env python3
"""
NARRATRON - The Dynamic Narrative Game Engine

A comic-book style interactive fiction game powered by AI.
"""

import os
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from src.state.static_config import StaticConfig
from src.state.game_state import GameState
from src.narratron.narratron import Narratron
from src.image_gen.image_generator import ImageGenerator, MockImageGenerator
from src.ui.terminal_ui import TerminalUI


class GameEngine:
    """Main game engine that orchestrates all components."""

    def __init__(
        self,
        config_dir: str = "config",
        use_real_images: bool = True,
        auto_generate_images: bool = True
    ):
        # Load environment variables
        load_dotenv()

        # Check for API key
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            print("Warning: OPENAI_API_KEY not found in environment.")
            print("Please set it in a .env file or export it as an environment variable.")
            print("Running in limited mode without AI features.\n")

        # Load static configuration
        self.config = StaticConfig.load_from_directory(config_dir)

        if not self.config.world_blueprint:
            raise ValueError("No world blueprint found. Cannot start game.")

        # Initialize components
        self.game_state: GameState | None = None
        self.ui = TerminalUI(self.config)

        # Initialize Narratron if API key available
        self.narratron: Narratron | None = None
        if self.api_key:
            self.narratron = Narratron(
                config=self.config,
                api_key=self.api_key,
                model="gpt-4o-mini"  # Use a fast, capable model
            )

        # Initialize image generator
        self.use_real_images = use_real_images and bool(self.api_key)
        self.auto_generate_images = auto_generate_images

        if self.use_real_images:
            self.image_gen = ImageGenerator(
                api_key=self.api_key,
                output_dir="assets/generated"
            )
        else:
            self.image_gen = MockImageGenerator(output_dir="assets/generated")

        # Image generation state
        self._last_image_path: str | None = None
        self._image_thread: threading.Thread | None = None

        # Save/load paths
        self.save_dir = Path("saves")
        self.save_dir.mkdir(exist_ok=True)

    def start_new_game(self) -> None:
        """Initialize a new game session."""
        self.game_state = GameState.initialize_from_config(self.config)

        # Generate opening scene if Narratron is available
        if self.narratron:
            self.ui.show_loading("Generating opening scene...")
            response = self.narratron.generate_opening_scene(self.game_state)
            opening_narrative = response.outcome_narrative

            # Start image generation in background
            if self.auto_generate_images:
                self._start_image_generation()
        else:
            # Fallback opening without AI
            opening_narrative = self._generate_fallback_opening()

        # Show the opening scene
        self.ui.show_scene(
            game_state=self.game_state,
            narrative_text=opening_narrative,
            image_path=self._last_image_path
        )

    def _generate_fallback_opening(self) -> str:
        """Generate opening text without AI."""
        bp = self.config.world_blueprint
        loc = self.config.get_location_by_id(bp.starting_location_id)
        return f"""
{bp.synopsis}

You find yourself in {loc.name if loc else 'an unknown place'}.

{loc.description if loc else 'Look around to get your bearings.'}

Your goal: {bp.goal}

(Note: Running in limited mode. Set OPENAI_API_KEY for full AI features.)
"""

    def _start_image_generation(self) -> None:
        """Start image generation in a background thread."""
        if not self.game_state:
            return

        def generate():
            try:
                path = self.image_gen.generate_image(
                    self.game_state.render,
                    visual_style=self.config.world_blueprint.visual_style
                )
                self._last_image_path = path
            except Exception as e:
                print(f"Image generation error: {e}")

        self._image_thread = threading.Thread(target=generate, daemon=True)
        self._image_thread.start()

    def process_player_input(self, player_input: str) -> bool:
        """
        Process player input and update the game state.
        Returns False if the game should end, True otherwise.
        """
        if not self.game_state:
            return False

        # Handle special commands
        command = player_input.lower().strip()

        if command in ("quit", "q", "exit"):
            if self.ui.confirm("Are you sure you want to quit?"):
                return False
            return True

        if command in ("help", "?"):
            self.ui.show_help()
            return True

        if command in ("inventory", "i", "inv"):
            self.ui.show_inventory(self.game_state)
            return True

        if command in ("status", "stats"):
            self.ui.show_full_status(self.game_state)
            return True

        if command in ("look", "l"):
            # Shortcut for looking around - pass to narratron as "look around"
            player_input = "look around"

        if command in ("hint", "h"):
            if self.narratron:
                hint = self.narratron.get_current_milestone_hint(self.game_state)
                self.ui.show_hint(hint)
            else:
                self.ui.show_message("Hints not available in limited mode.", "yellow")
            return True

        if command == "save":
            self._save_game()
            return True

        if command == "load":
            self._load_game()
            return True

        # Process game action
        if self.narratron:
            self.ui.show_loading("Processing your action...")
            response = self.narratron.process_action(player_input, self.game_state)

            # Start image generation in background
            if self.auto_generate_images:
                self._start_image_generation()

            # Show the result
            self.ui.show_scene(
                game_state=self.game_state,
                narrative_text=response.outcome_narrative,
                image_path=self._last_image_path,
                milestone_completed=response.milestone_completed
            )

            # Check for game over conditions
            if self.game_state.player.health <= 0:
                self.ui.show_game_over(won=False, game_state=self.game_state)
                return False

            # Check for victory
            if self._check_victory():
                self.ui.show_game_over(won=True, game_state=self.game_state)
                return False

        else:
            # Limited mode response
            self.ui.show_message(
                f"You try to: {player_input}\n\n"
                "[Limited mode - AI processing unavailable]",
                "yellow"
            )

        return True

    def _check_victory(self) -> bool:
        """Check if the player has won the game."""
        if not self.game_state:
            return False

        # Victory when all milestones are completed
        total_milestones = len(self.config.milestones)
        completed = len(self.game_state.checkpoints.completed_milestones)

        return total_milestones > 0 and completed >= total_milestones

    def _save_game(self) -> None:
        """Save the current game state."""
        if not self.game_state:
            self.ui.show_error("No game in progress to save.")
            return

        filename = f"save_{self.game_state.meta.session_id[:8]}.json"
        filepath = self.save_dir / filename

        try:
            self.game_state.save_to_file(filepath)
            self.ui.show_message(f"Game saved to {filename}", "green")
        except Exception as e:
            self.ui.show_error(f"Failed to save game: {e}")

    def _load_game(self) -> None:
        """Load a saved game."""
        saves = [f.name for f in self.save_dir.glob("save_*.json")]

        if not saves:
            self.ui.show_message("No saved games found.", "yellow")
            return

        selected = self.ui.show_save_load_menu(saves)
        if not selected:
            return

        try:
            filepath = self.save_dir / selected
            self.game_state = GameState.load_from_file(filepath)
            self.ui.show_message(f"Game loaded from {selected}", "green")

            # Show current scene
            self.ui.show_scene(
                game_state=self.game_state,
                narrative_text=self.game_state.narrative.current_scene or "Game loaded.",
                image_path=self._last_image_path
            )
        except Exception as e:
            self.ui.show_error(f"Failed to load game: {e}")

    def run(self) -> None:
        """Main game loop."""
        # Show title screen
        self.ui.show_title_screen()

        # Start new game
        self.start_new_game()

        # Main game loop
        running = True
        while running:
            # Show status bar
            self.ui.show_status_bar(self.game_state)

            # Get player input
            player_input = self.ui.get_player_input()

            if not player_input:
                continue

            # Process input
            running = self.process_player_input(player_input)

        self.ui.show_message("\nThanks for playing NARRATRON!", "cyan")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="NARRATRON - Dynamic Narrative Game Engine")
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory containing game configuration files"
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Disable image generation"
    )
    parser.add_argument(
        "--mock-images",
        action="store_true",
        help="Use mock image generation (no API calls)"
    )

    args = parser.parse_args()

    try:
        engine = GameEngine(
            config_dir=args.config_dir,
            use_real_images=not args.mock_images,
            auto_generate_images=not args.no_images
        )
        engine.run()
    except KeyboardInterrupt:
        print("\n\nGame interrupted. Goodbye!")
    except Exception as e:
        print(f"\nFatal error: {e}")
        raise


if __name__ == "__main__":
    main()
