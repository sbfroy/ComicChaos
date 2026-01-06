"""Setting registry for managing multiple comic settings."""

import json
from pathlib import Path
from pydantic import BaseModel, Field


class SettingInfo(BaseModel):
    """Metadata about a registered setting."""

    id: str = Field(description="Unique setting identifier (directory name)")
    name: str = Field(description="Display name")
    description: str = Field(description="Brief description")
    style: str = Field(description="Visual style description")


class SettingRegistry:
    """Registry for discovering and managing multiple comic settings."""

    def __init__(self, settings_dir: str | Path = "settings"):
        self.settings_dir = Path(settings_dir)
        self._settings: dict[str, SettingInfo] = {}
        self._discover_settings()

    def _discover_settings(self) -> None:
        """Discover all available settings."""
        if not self.settings_dir.exists():
            return

        for setting_path in self.settings_dir.iterdir():
            if setting_path.is_dir():
                blueprint_file = setting_path / "blueprint.json"
                if blueprint_file.exists():
                    # Load info from blueprint
                    with open(blueprint_file) as f:
                        bp_data = json.load(f)
                    self._settings[setting_path.name] = SettingInfo(
                        id=setting_path.name,
                        name=bp_data.get("title", setting_path.name),
                        description=bp_data.get("synopsis", "No description"),
                        style=bp_data.get("visual_style", "comic book style")
                    )

    def get_available_settings(self) -> list[SettingInfo]:
        """Get list of all available settings."""
        return list(self._settings.values())

    def get_setting(self, setting_id: str) -> SettingInfo | None:
        """Get info for a specific setting."""
        return self._settings.get(setting_id)

    def get_setting_config_dir(self, setting_id: str) -> Path | None:
        """Get the config directory for a setting."""
        setting_dir = self.settings_dir / setting_id
        if setting_dir.exists():
            return setting_dir
        return None

    def list_settings(self) -> str:
        """Get a formatted list of available settings."""
        if not self._settings:
            return "No settings found in the settings directory."

        lines = ["Available Settings:", ""]
        for i, (setting_id, info) in enumerate(self._settings.items(), 1):
            lines.append(f"  [{i}] {info.name}")
            lines.append(f"      {info.description[:80]}...")
            lines.append(f"      Style: {info.style[:50]}...")
            lines.append("")

        return "\n".join(lines)
