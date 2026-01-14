#!/usr/bin/env python3
"""
Comic Creator - Interactive Comic Strip Generator

Create your own comic strips by describing what happens next!
"""

import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

from src.config import (
    LLM_MODEL,
    GENERATED_IMAGES_DIR,
    SETTINGS_DIR,
)
from src.state.static_config import StaticConfig
from src.state.comic_state import ComicState
from settings.setting_registry import SettingRegistry, SettingInfo
from src.narratron.narratron import Narratron
from src.image_gen.image_generator import ImageGenerator, MockImageGenerator
from src.comic_strip import ComicStrip


console = Console()


class ComicCreator:
    """Main engine for creating interactive comics."""

    def __init__(
        self,
        config_dir: str,
        use_real_images: bool = True,
        auto_show_images: bool = True
    ):
        load_dotenv()

        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            console.print("[yellow]Warning: OPENAI_API_KEY not found.[/yellow]")
            console.print("Please set it in a .env file for full features.\n")

        # Load configuration
        self.config = StaticConfig.load_from_directory(config_dir)

        if not self.config.blueprint:
            raise ValueError("No blueprint found. Cannot start.")

        # Initialize state
        self.state: ComicState | None = None
        self.auto_show_images = auto_show_images

        # Initialize Narratron
        self.narratron: Narratron | None = None
        if self.api_key:
            self.narratron = Narratron(
                config=self.config,
                api_key=self.api_key
            )

        # Initialize image generator
        if use_real_images and self.api_key:
            self.image_gen = ImageGenerator(api_key=self.api_key)
        else:
            self.image_gen = MockImageGenerator()

        # Comic strip collector
        self.comic_strip: ComicStrip | None = None

        # Image generation state
        self._current_image_path: str | None = None
        self._image_thread: threading.Thread | None = None
        self._image_ready = threading.Event()

    def start(self) -> None:
        """Start a new comic creation session."""
        self.state = ComicState.initialize_from_config(self.config)

        # Initialize comic strip collector
        title = self.config.blueprint.title if self.config.blueprint else "My Comic"
        self.comic_strip = ComicStrip(title=title)

        # Generate opening panel
        if self.narratron:
            console.print("\n[dim]Creating opening panel...[/dim]")
            response = self.narratron.generate_opening_panel(self.state)
            narrative = response.panel_narrative

            # Generate image and wait for it
            self._generate_image_sync()

            # Add panel to comic strip
            self.state.add_panel(narrative, self._current_image_path)
            self.comic_strip.add_panel(self._current_image_path, narrative, 1)

            # Show the panel
            self._show_panel(narrative)
        else:
            narrative = self._fallback_opening()
            self._show_panel(narrative)

    def _generate_image_sync(self) -> None:
        """Generate an image and wait for completion."""
        if not self.state:
            return

        try:
            path = self.image_gen.generate_image(
                self.state.render,
                visual_style=self.config.blueprint.visual_style
            )
            self._current_image_path = path
        except Exception as e:
            console.print(f"[dim]Image generation: {e}[/dim]")
            self._current_image_path = None

    def _show_panel(self, narrative: str) -> None:
        """Display a comic panel."""
        panel_num = self.state.meta.panel_count if self.state else 0

        # Show narrative
        console.print()
        console.print(Panel(
            Text(narrative, style="bold"),
            title=f"Panel {panel_num}",
            border_style="cyan"
        ))

        # Show and open image
        if self._current_image_path:
            console.print(f"[dim]Image: {self._current_image_path}[/dim]")
            if self.auto_show_images and self.comic_strip:
                self.comic_strip.show_panel(self._current_image_path)

    def _fallback_opening(self) -> str:
        """Generate opening without AI."""
        bp = self.config.blueprint
        loc = bp.starting_location
        return f"{bp.synopsis}\n\nThe scene opens at {loc.name}."

    def process_input(self, user_input: str) -> None:
        """Process user input to create the next panel."""
        if not self.state:
            return

        if self.narratron:
            console.print("\n[dim]Creating next panel...[/dim]")
            response = self.narratron.process_input(user_input, self.state)

            # Show if new entities were introduced
            if response.new_location:
                loc_name = response.new_location.get("name", "unknown")
                console.print(f"[green]New location discovered: {loc_name}[/green]")

            if response.new_character:
                char_name = response.new_character.get("name", "unknown")
                console.print(f"[green]New character introduced: {char_name}[/green]")

            narrative = response.panel_narrative

            # Generate image
            self._generate_image_sync()

            # Add to comic strip
            self.state.add_panel(narrative, self._current_image_path)
            if self.comic_strip:
                self.comic_strip.add_panel(
                    self._current_image_path,
                    narrative,
                    self.state.meta.panel_count
                )

            # Show the panel
            self._show_panel(narrative)
        else:
            console.print("[yellow]AI not available. Set OPENAI_API_KEY.[/yellow]")

    def finish(self) -> None:
        """Finish the session and show the final comic."""
        if self.comic_strip and self.comic_strip.get_panel_count() > 0:
            console.print("\n[bold green]Creating your comic strip...[/bold green]")
            strip_path = self.comic_strip.show_final_comic()

            if strip_path:
                console.print(f"\n[bold]Your comic has been saved![/bold]")
                console.print(f"[cyan]{strip_path}[/cyan]")
            else:
                console.print("[yellow]Could not generate comic strip.[/yellow]")

            # Show summary
            console.print(f"\n[dim]Total panels: {self.comic_strip.get_panel_count()}[/dim]")

    def run(self) -> None:
        """Main loop."""
        self._show_title()
        self.start()

        while True:
            console.print()
            try:
                user_input = Prompt.ask("[bold cyan]What happens next?[/bold cyan]")
                if not user_input.strip():
                    continue
                self.process_input(user_input)
            except (KeyboardInterrupt, EOFError):
                break

        self.finish()
        console.print("\n[cyan]Thanks for creating with Comic Chaos![/cyan]\n")

    def _show_title(self) -> None:
        """Show the title screen."""
        if self.config.blueprint:
            bp = self.config.blueprint
            title = f"""
[bold cyan]{'=' * 50}[/bold cyan]
[bold]  COMIC CHAOS[/bold]
[bold cyan]{'=' * 50}[/bold cyan]

[bold]{bp.title}[/bold]

{bp.synopsis[:200]}...

[dim]Style: {bp.visual_style[:50]}...[/dim]

[bold green]Type what you want to happen to create comic panels![/bold green]
[dim]Press Ctrl+C when finished to generate your comic strip.[/dim]
"""
            console.print(title)


def show_comic_selection(registry: SettingRegistry) -> SettingInfo | None:
    """Display comic selection menu."""
    settings = registry.get_available_settings()

    if not settings:
        console.print("\n[yellow]No settings found in 'settings' directory.[/yellow]")
        return None

    console.print("\n[bold cyan]" + "=" * 50 + "[/bold cyan]")
    console.print("[bold]  COMIC CREATOR - Choose Your Setting[/bold]")
    console.print("[bold cyan]" + "=" * 50 + "[/bold cyan]\n")

    for i, setting in enumerate(settings, 1):
        console.print(f"  [bold][{i}][/bold] {setting.name}")
        console.print(f"      [dim]{setting.description[:60]}...[/dim]")
        console.print(f"      [italic]Style: {setting.style[:40]}...[/italic]\n")

    console.print("  [bold][0][/bold] Exit\n")

    while True:
        try:
            choice = Prompt.ask("Select a setting").strip()

            if choice == "0":
                return None

            idx = int(choice) - 1
            if 0 <= idx < len(settings):
                return settings[idx]
            else:
                console.print("[yellow]Invalid selection.[/yellow]")
        except ValueError:
            console.print("[yellow]Please enter a number.[/yellow]")
        except KeyboardInterrupt:
            return None


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Comic Creator - Interactive Comic Strip Generator")
    parser.add_argument("--config-dir", default=None, help="Comic configuration directory")
    parser.add_argument("--comic", default=None, help="Comic ID to load directly")
    parser.add_argument("--no-images", action="store_true", help="Disable image generation")
    parser.add_argument("--mock-images", action="store_true", help="Use mock images (no API)")
    parser.add_argument("--no-auto-show", action="store_true", help="Don't auto-open images")
    parser.add_argument("--list", action="store_true", help="List available comics")

    args = parser.parse_args()

    registry = SettingRegistry(settings_dir=SETTINGS_DIR)

    if args.list:
        console.print(registry.list_settings())
        return

    config_dir = args.config_dir

    if config_dir is None:
        if args.comic:
            config_dir = registry.get_setting_config_dir(args.comic)
            if config_dir is None:
                console.print(f"[red]Setting '{args.comic}' not found.[/red]")
                console.print(registry.list_settings())
                return
        else:
            selected = show_comic_selection(registry)
            if selected is None:
                console.print("\n[cyan]Goodbye![/cyan]")
                return

            config_dir = registry.get_setting_config_dir(selected.id)
            if config_dir is None:
                console.print(f"[red]Could not find config for '{selected.id}'[/red]")
                return

    try:
        creator = ComicCreator(
            config_dir=str(config_dir),
            use_real_images=not args.mock_images and not args.no_images,
            auto_show_images=not args.no_auto_show
        )
        creator.run()
    except KeyboardInterrupt:
        console.print("\n\n[cyan]Goodbye![/cyan]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
