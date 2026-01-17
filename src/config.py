"""Central configuration for all technical settings.

All model parameters, API settings, and paths are defined here.
"""

# =============================================================================
# LLM Settings (Narratron)
# =============================================================================
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0.6
LLM_MAX_TOKENS = 1500

# =============================================================================
# Image Generation Settings
# =============================================================================
IMAGE_MODEL = "gpt-image-1-mini"  # Alternative: "dall-e-3"
IMAGE_SIZE = "1024x1024"
IMAGE_QUALITY = "medium"  # Options: "low", "medium", "high"
IMAGE_MODERATION = "low"

# =============================================================================
# Output Directories
# =============================================================================
GENERATED_IMAGES_DIR = "assets/generated"
COMIC_STRIPS_DIR = "assets/comics"

# =============================================================================
# Settings Directory
# =============================================================================
SETTINGS_DIR = "settings"
