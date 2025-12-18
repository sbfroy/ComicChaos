#!/usr/bin/env python3
"""Verify that the game setup is correct and all components load properly."""

import sys
from pathlib import Path


def verify_setup():
    """Run verification checks on the game setup."""
    print("NARRATRON Setup Verification")
    print("=" * 40)
    errors = []
    warnings = []

    # Check Python version
    print("\n1. Checking Python version...")
    if sys.version_info < (3, 10):
        errors.append(f"Python 3.10+ required, found {sys.version}")
    else:
        print(f"   OK: Python {sys.version_info.major}.{sys.version_info.minor}")

    # Check required files
    print("\n2. Checking required files...")
    required_files = [
        "config/world_blueprint.json",
        "config/constraints.json",
        "config/milestones.json",
        "main.py",
        "requirements.txt",
    ]
    for f in required_files:
        if Path(f).exists():
            print(f"   OK: {f}")
        else:
            errors.append(f"Missing required file: {f}")

    # Try importing modules
    print("\n3. Checking module imports...")
    try:
        from src.state.static_config import StaticConfig
        print("   OK: StaticConfig")
    except ImportError as e:
        errors.append(f"Failed to import StaticConfig: {e}")

    try:
        from src.state.game_state import GameState
        print("   OK: GameState")
    except ImportError as e:
        errors.append(f"Failed to import GameState: {e}")

    try:
        from src.narratron.narratron import Narratron
        print("   OK: Narratron")
    except ImportError as e:
        errors.append(f"Failed to import Narratron: {e}")

    try:
        from src.image_gen.image_generator import ImageGenerator
        print("   OK: ImageGenerator")
    except ImportError as e:
        errors.append(f"Failed to import ImageGenerator: {e}")

    try:
        from src.ui.terminal_ui import TerminalUI
        print("   OK: TerminalUI")
    except ImportError as e:
        errors.append(f"Failed to import TerminalUI: {e}")

    # Try loading configuration
    print("\n4. Loading game configuration...")
    try:
        from src.state.static_config import StaticConfig
        config = StaticConfig.load_from_directory("config")
        print(f"   OK: Loaded {len(config.constraints)} constraints")
        print(f"   OK: Loaded {len(config.milestones)} milestones")
        if config.world_blueprint:
            print(f"   OK: World blueprint '{config.world_blueprint.title}'")
            print(f"       - {len(config.world_blueprint.locations)} locations")
            print(f"       - {len(config.world_blueprint.characters)} characters")
            print(f"       - {len(config.world_blueprint.items)} items")
        else:
            errors.append("No world blueprint found")
    except Exception as e:
        errors.append(f"Failed to load configuration: {e}")

    # Try initializing game state
    print("\n5. Initializing game state...")
    try:
        from src.state.game_state import GameState
        game_state = GameState.initialize_from_config(config)
        print(f"   OK: Game state initialized")
        print(f"       - Starting location: {game_state.player.location_id}")
        print(f"       - Session ID: {game_state.meta.session_id[:8]}...")
    except Exception as e:
        errors.append(f"Failed to initialize game state: {e}")

    # Check for API key
    print("\n6. Checking environment...")
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        print(f"   OK: OPENAI_API_KEY found ({len(api_key)} chars)")
    else:
        warnings.append("OPENAI_API_KEY not set - game will run in limited mode")
        print("   WARN: OPENAI_API_KEY not set")

    # Summary
    print("\n" + "=" * 40)
    if errors:
        print("\nERRORS:")
        for err in errors:
            print(f"  - {err}")
        print(f"\nVerification FAILED with {len(errors)} error(s)")
        return False
    else:
        if warnings:
            print("\nWARNINGS:")
            for warn in warnings:
                print(f"  - {warn}")
        print("\nVerification PASSED!")
        print("\nTo start the game, run:")
        print("  python main.py")
        if warnings:
            print("\nNote: Set OPENAI_API_KEY in .env for full AI features")
        return True


if __name__ == "__main__":
    success = verify_setup()
    sys.exit(0 if success else 1)
