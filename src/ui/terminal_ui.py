"""Terminal-based UI for the narrative game using Rich."""

import os
import sys
import subprocess
import platform
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.markdown import Markdown
from rich.style import Style
from rich.box import ROUNDED, DOUBLE, HEAVY
from rich import print as rprint

from ..state.game_state import GameState
from ..state.static_config import StaticConfig


def is_wsl() -> bool:
    """Check if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def open_image(image_path: str) -> bool:
    """Open an image in the system's default viewer."""
    try:
        path = Path(image_path).absolute()
        if not path.exists():
            return False

        system = platform.system()

        if system == "Darwin":  # macOS
            subprocess.run(["open", str(path)], check=True)
        elif system == "Windows":
            os.startfile(str(path))
        elif is_wsl():
            # WSL: Convert path to Windows path and use explorer.exe
            try:
                # Try wslview first (from wslu package)
                subprocess.run(["wslview", str(path)], check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fall back to explorer.exe with wslpath conversion
                try:
                    # Convert Linux path to Windows path
                    result = subprocess.run(
                        ["wslpath", "-w", str(path)],
                        capture_output=True, text=True, check=True
                    )
                    win_path = result.stdout.strip()
                    subprocess.run(["explorer.exe", win_path], check=True)
                except Exception:
                    # Last resort: try powershell
                    result = subprocess.run(
                        ["wslpath", "-w", str(path)],
                        capture_output=True, text=True, check=True
                    )
                    win_path = result.stdout.strip()
                    subprocess.run(
                        ["powershell.exe", "-Command", f'Start-Process "{win_path}"'],
                        check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL
                    )
        else:  # Linux
            try:
                subprocess.run(["xdg-open", str(path)], check=True, stderr=subprocess.DEVNULL)
            except (subprocess.CalledProcessError, FileNotFoundError):
                webbrowser.open(f"file://{path}")
        return True
    except Exception as e:
        print(f"Could not open image: {e}")
        return False


class TerminalUI:
    """Rich terminal interface for the narrative game."""

    def __init__(self, config: StaticConfig, auto_open_images: bool = True):
        self.console = Console()
        self.config = config
        self._last_image_path: str | None = None
        self.auto_open_images = auto_open_images

    def clear_screen(self) -> None:
        """Clear the terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def show_title_screen(self) -> None:
        """Display the game title screen."""
        self.clear_screen()

        if self.config.world_blueprint:
            title = self.config.world_blueprint.title
            synopsis = self.config.world_blueprint.synopsis
        else:
            title = "NARRATRON"
            synopsis = "An interactive narrative adventure"

        title_art = """
    ╔═══════════════════════════════════════════════════════════════════════╗
    ║                                                                       ║
    ║   ███╗   ██╗ █████╗ ██████╗ ██████╗  █████╗ ████████╗██████╗  ██████╗ ███╗   ██╗  ║
    ║   ████╗  ██║██╔══██╗██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔═══██╗████╗  ██║  ║
    ║   ██╔██╗ ██║███████║██████╔╝██████╔╝███████║   ██║   ██████╔╝██║   ██║██╔██╗ ██║  ║
    ║   ██║╚██╗██║██╔══██║██╔══██╗██╔══██╗██╔══██║   ██║   ██╔══██╗██║   ██║██║╚██╗██║  ║
    ║   ██║ ╚████║██║  ██║██║  ██║██║  ██║██║  ██║   ██║   ██║  ██║╚██████╔╝██║ ╚████║  ║
    ║   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝  ║
    ║                                                                       ║
    ║                    The Dynamic Narrative Engine                       ║
    ║                                                                       ║
    ╚═══════════════════════════════════════════════════════════════════════╝
"""

        self.console.print(title_art, style="bold cyan")
        self.console.print()

        # Game title
        self.console.print(Panel(
            Text(title, justify="center", style="bold yellow"),
            box=DOUBLE,
            border_style="yellow"
        ))

        self.console.print()

        # Synopsis
        self.console.print(Panel(
            synopsis,
            title="[bold]The Story[/bold]",
            box=ROUNDED,
            border_style="blue"
        ))

        self.console.print()
        self.console.print("[dim]Press ENTER to begin your adventure...[/dim]", justify="center")
        input()

    def show_scene(
        self,
        game_state: GameState,
        narrative_text: str,
        image_path: str | None = None,
        milestone_completed: str | None = None
    ) -> None:
        """Display the current scene."""
        self.clear_screen()

        # Header with turn count and location
        location = self.config.get_location_by_id(game_state.player.location_id)
        location_name = location.name if location else game_state.player.location_id

        header_table = Table(show_header=False, box=None, padding=(0, 2))
        header_table.add_column(justify="left")
        header_table.add_column(justify="right")
        header_table.add_row(
            f"[bold cyan]📍 {location_name}[/bold cyan]",
            f"[dim]Turn {game_state.meta.turn_count}[/dim]"
        )
        self.console.print(header_table)
        self.console.print()

        # Milestone completion notification
        if milestone_completed:
            milestone = self.config.get_milestone_by_id(milestone_completed)
            milestone_name = milestone.name if milestone else milestone_completed
            self.console.print(Panel(
                f"[bold green]✨ CHECKPOINT REACHED ✨[/bold green]\n\n{milestone_name}",
                box=DOUBLE,
                border_style="green"
            ))
            self.console.print()

        # Story panel
        self.console.print(Panel(
            narrative_text,
            title="[bold white]📖 Story[/bold white]",
            box=ROUNDED,
            border_style="white",
            padding=(1, 2)
        ))
        self.console.print()

        # Image indicator (if image was generated)
        if image_path:
            self._last_image_path = image_path
            if self.auto_open_images:
                if open_image(image_path):
                    self.console.print(
                        f"[dim]🎨 Scene illustration opened in viewer[/dim]",
                        justify="center"
                    )
                else:
                    self.console.print(
                        f"[dim]🎨 Scene illustration: {Path(image_path).name}[/dim]",
                        justify="center"
                    )
            else:
                self.console.print(
                    f"[dim]🎨 Scene illustration: {Path(image_path).name}[/dim]",
                    justify="center"
                )
            self.console.print()

        # Current scene description
        if game_state.narrative.current_scene:
            self.console.print(Panel(
                game_state.narrative.current_scene,
                title="[bold blue]👁 Current Scene[/bold blue]",
                box=ROUNDED,
                border_style="blue",
                padding=(1, 2)
            ))
            self.console.print()

    def show_status_bar(self, game_state: GameState) -> None:
        """Display the status bar with player info."""
        # Build inventory string
        inventory = game_state.player.inventory
        inv_str = ", ".join(inventory[:5]) if inventory else "empty"
        if len(inventory) > 5:
            inv_str += f" (+{len(inventory) - 5} more)"

        # Build milestone progress
        completed = len(game_state.checkpoints.completed_milestones)
        total = len(self.config.milestones)
        progress = f"{completed}/{total}" if total > 0 else "N/A"

        # Create status table
        status_table = Table(box=ROUNDED, show_header=True, header_style="bold")
        status_table.add_column("❤️ Health", justify="center")
        status_table.add_column("🎒 Inventory", justify="center")
        status_table.add_column("⭐ Progress", justify="center")

        health_style = "green" if game_state.player.health > 50 else "yellow" if game_state.player.health > 25 else "red"
        status_table.add_row(
            f"[{health_style}]{game_state.player.health}%[/{health_style}]",
            inv_str,
            progress
        )

        self.console.print(status_table)
        self.console.print()

    def show_hint(self, hint: str | None) -> None:
        """Display a hint for the current objective."""
        if hint:
            self.console.print(Panel(
                f"[italic]{hint}[/italic]",
                title="[bold yellow]💡 Hint[/bold yellow]",
                box=ROUNDED,
                border_style="yellow"
            ))
            self.console.print()

    def get_player_input(self) -> str:
        """Get input from the player."""
        self.console.print("[bold green]>[/bold green] ", end="")
        try:
            action = input().strip()
            return action
        except EOFError:
            return "quit"
        except KeyboardInterrupt:
            return "quit"

    def show_help(self) -> None:
        """Display help information."""
        help_text = """
[bold]MOVEMENT & EXPLORATION:[/bold]
  [cyan]look[/cyan] / [cyan]l[/cyan]         - Look around the current location
  [cyan]go [direction][/cyan]  - Move in a direction (north, south, east, west, etc.)
  [cyan]exits[/cyan] / [cyan]map[/cyan]      - Show available exits from current location
  [cyan]examine [thing][/cyan] - Examine something more closely

[bold]INTERACTION:[/bold]
  [cyan]talk [person][/cyan]   - Talk to a character
  [cyan]take [item][/cyan]     - Pick up an item
  [cyan]use [item][/cyan]      - Use an item
  [cyan]give [item] to [person][/cyan] - Give an item to someone

[bold]INFORMATION:[/bold]
  [cyan]inventory[/cyan] / [cyan]i[/cyan]    - Check your inventory
  [cyan]status[/cyan]          - View your full status and progress
  [cyan]hint[/cyan] / [cyan]h[/cyan]         - Get a hint for your current objective
  [cyan]image[/cyan]           - Show info about the current scene image

[bold]GAME:[/bold]
  [cyan]save[/cyan]            - Save your game
  [cyan]load[/cyan]            - Load a saved game
  [cyan]help[/cyan] / [cyan]?[/cyan]         - Show this help
  [cyan]quit[/cyan] / [cyan]q[/cyan]         - Quit the game

[bold]TIPS:[/bold]
  - You can try ANY action! Be creative!
  - Some actions may not advance the story, but you'll get interesting responses
  - Pay attention to descriptions - they contain clues
  - The game auto-saves every 5 turns
  - Not everything is as it seems...
"""
        self.console.print(Panel(
            help_text,
            title="[bold]Help[/bold]",
            box=ROUNDED,
            border_style="cyan"
        ))

    def show_inventory(self, game_state: GameState) -> None:
        """Display the player's inventory."""
        if not game_state.player.inventory:
            self.console.print(Panel(
                "[italic]Your inventory is empty.[/italic]",
                title="[bold]🎒 Inventory[/bold]",
                box=ROUNDED,
                border_style="cyan"
            ))
            return

        items_table = Table(box=ROUNDED, show_header=True, header_style="bold")
        items_table.add_column("Item", style="cyan")
        items_table.add_column("Description")

        for item_id in game_state.player.inventory:
            item = self.config.get_item_by_id(item_id)
            if item:
                items_table.add_row(item.name, item.description)
            else:
                items_table.add_row(item_id, "[dim]Unknown item[/dim]")

        self.console.print(Panel(
            items_table,
            title="[bold]🎒 Inventory[/bold]",
            box=ROUNDED,
            border_style="cyan"
        ))

    def show_full_status(self, game_state: GameState) -> None:
        """Display full player status."""
        self.show_status_bar(game_state)

        # Known information
        if game_state.player.known_information:
            info_text = "\n".join(f"• {info}" for info in game_state.player.known_information)
            self.console.print(Panel(
                info_text,
                title="[bold]📚 Known Information[/bold]",
                box=ROUNDED,
                border_style="magenta"
            ))

        # Completed milestones
        if game_state.checkpoints.completed_milestones:
            milestones_text = ""
            for m_id in game_state.checkpoints.completed_milestones:
                milestone = self.config.get_milestone_by_id(m_id)
                name = milestone.name if milestone else m_id
                milestones_text += f"✅ {name}\n"
            self.console.print(Panel(
                milestones_text.strip(),
                title="[bold]⭐ Completed Checkpoints[/bold]",
                box=ROUNDED,
                border_style="green"
            ))

        # Current objective
        if game_state.checkpoints.current_milestone_id:
            milestone = self.config.get_milestone_by_id(game_state.checkpoints.current_milestone_id)
            if milestone:
                self.console.print(Panel(
                    f"[bold]{milestone.name}[/bold]\n{milestone.description}",
                    title="[bold]🎯 Current Objective[/bold]",
                    box=ROUNDED,
                    border_style="yellow"
                ))

    def show_error(self, message: str) -> None:
        """Display an error message."""
        self.console.print(Panel(
            message,
            title="[bold red]Error[/bold red]",
            box=ROUNDED,
            border_style="red"
        ))

    def show_message(self, message: str, style: str = "white") -> None:
        """Display a simple message."""
        self.console.print(f"[{style}]{message}[/{style}]")

    def show_game_over(self, won: bool, game_state: GameState) -> None:
        """Display the game over screen."""
        self.clear_screen()

        if won:
            title = "[bold green]🎉 VICTORY! 🎉[/bold green]"
            message = "Congratulations! You have completed the adventure!"
            border_style = "green"
        else:
            title = "[bold red]💀 GAME OVER 💀[/bold red]"
            message = "Your adventure has come to an end..."
            border_style = "red"

        self.console.print(Panel(
            f"{title}\n\n{message}\n\n[dim]Turns taken: {game_state.meta.turn_count}[/dim]",
            box=DOUBLE,
            border_style=border_style
        ))

        # Show story summary
        self.console.print()
        self.console.print(Panel(
            game_state.narrative.rolling_summary,
            title="[bold]Your Story[/bold]",
            box=ROUNDED,
            border_style="blue"
        ))

    def show_loading(self, message: str = "Processing...") -> None:
        """Display a loading indicator."""
        self.console.print(f"[dim italic]{message}[/dim italic]")

    def confirm(self, message: str) -> bool:
        """Ask for confirmation."""
        self.console.print(f"{message} [dim](y/n)[/dim] ", end="")
        response = input().strip().lower()
        return response in ("y", "yes")

    def show_save_load_menu(self, saves: list[str]) -> str | None:
        """Display save/load menu and return selected save or None."""
        if not saves:
            self.console.print("[dim]No saved games found.[/dim]")
            return None

        self.console.print("[bold]Saved Games:[/bold]")
        for i, save in enumerate(saves, 1):
            self.console.print(f"  [{i}] {save}")
        self.console.print(f"  [0] Cancel")
        self.console.print()
        self.console.print("Select a save: ", end="")

        try:
            choice = int(input().strip())
            if 1 <= choice <= len(saves):
                return saves[choice - 1]
        except (ValueError, IndexError):
            pass

        return None
