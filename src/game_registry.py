"""Comic registry for managing multiple comic worlds."""

import json
from pathlib import Path
from pydantic import BaseModel, Field


class GameInfo(BaseModel):
    """Metadata about a registered comic."""

    id: str = Field(description="Unique comic identifier (directory name)")
    name: str = Field(description="Display name")
    description: str = Field(description="Brief description")
    style: str = Field(description="Visual style description")
    author: str = Field(default="Unknown", description="Creator")
    version: str = Field(default="1.0.0", description="Version")

    @classmethod
    def load_from_directory(cls, game_dir: Path) -> "GameInfo | None":
        """Load comic info from a directory."""
        info_file = game_dir / "game_info.json"
        if not info_file.exists():
            return None

        with open(info_file) as f:
            data = json.load(f)

        data["id"] = game_dir.name
        return cls(**data)


class GameRegistry:
    """Registry for discovering and managing multiple comics."""

    def __init__(self, games_dir: str | Path = "games"):
        self.games_dir = Path(games_dir)
        self._games: dict[str, GameInfo] = {}
        self._discover_games()

    def _discover_games(self) -> None:
        """Discover all available comics."""
        if not self.games_dir.exists():
            return

        for game_path in self.games_dir.iterdir():
            if game_path.is_dir():
                blueprint = game_path / "world_blueprint.json"
                if blueprint.exists():
                    info = GameInfo.load_from_directory(game_path)
                    if info:
                        self._games[info.id] = info
                    else:
                        # Create basic info from blueprint
                        with open(blueprint) as f:
                            bp_data = json.load(f)
                        self._games[game_path.name] = GameInfo(
                            id=game_path.name,
                            name=bp_data.get("title", game_path.name),
                            description=bp_data.get("synopsis", "No description"),
                            style=bp_data.get("visual_style", "comic book style")
                        )

    def get_available_games(self) -> list[GameInfo]:
        """Get list of all available comics."""
        return list(self._games.values())

    def get_game(self, game_id: str) -> GameInfo | None:
        """Get info for a specific comic."""
        return self._games.get(game_id)

    def get_game_config_dir(self, game_id: str) -> Path | None:
        """Get the config directory for a comic."""
        game_dir = self.games_dir / game_id
        if game_dir.exists():
            return game_dir
        return None

    def list_games(self) -> str:
        """Get a formatted list of available comics."""
        if not self._games:
            return "No comics found in the games directory."

        lines = ["Available Comics:", ""]
        for i, (game_id, info) in enumerate(self._games.items(), 1):
            lines.append(f"  [{i}] {info.name}")
            lines.append(f"      {info.description[:80]}...")
            lines.append(f"      Style: {info.style[:50]}...")
            lines.append("")

        return "\n".join(lines)
