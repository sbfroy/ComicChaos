"""Interaction logger for tracking LLM prompts and responses.

This module provides logging functionality to capture all interactions
between the system and LLM services (narrative generation and image generation).
The logs are saved in JSON format for easy analysis and review.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


class InteractionLogger:
    """Logs all LLM interactions during comic creation.
    
    Captures prompts, responses, and metadata for both narrative generation
    and image generation. Each comic session gets its own log file.
    
    Attributes:
        session_id: Unique identifier for this comic creation session.
        log_dir: Directory where log files are saved.
        log_file: Path to the current session's log file.
        interactions: List of all logged interactions in this session.
    """

    def __init__(self, comic_title: str = "comic", log_dir: str = "logs"):
        """Initialize the interaction logger.
        
        Args:
            comic_title: Title of the comic being created (used in filename).
            log_dir: Directory to save log files (created if doesn't exist).
        """
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize title for filename
        safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' 
                           for c in comic_title)
        safe_title = safe_title.replace(' ', '_')[:50]
        
        self.log_file = self.log_dir / f"{safe_title}_{self.session_id}.json"
        self.interactions: List[Dict[str, Any]] = []
        
        # Initialize the log file with metadata
        self._save_metadata(comic_title)

    def _save_metadata(self, comic_title: str) -> None:
        """Save session metadata to log file."""
        metadata = {
            "session_id": self.session_id,
            "comic_title": comic_title,
            "start_time": datetime.now().isoformat(),
            "interactions": []
        }
        
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def log_narrative_interaction(
        self,
        system_prompt: str,
        user_message: str,
        response: str,
        parsed_response: Optional[Dict[str, Any]] = None,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> None:
        """Log a narrative generation interaction.
        
        Args:
            system_prompt: The system prompt sent to the LLM.
            user_message: The user message sent to the LLM.
            response: The raw response from the LLM.
            parsed_response: The parsed JSON response (if available).
            model: The LLM model used.
            temperature: Temperature parameter used.
            max_tokens: Max tokens parameter used.
        """
        interaction = {
            "type": "narrative_generation",
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens
            },
            "prompt": {
                "system": system_prompt,
                "user": user_message
            },
            "response": {
                "raw": response,
                "parsed": parsed_response
            }
        }
           
        
        self._append_interaction(interaction)

    def log_image_generation(
        self,
        prompt: str,
        image_path: Optional[str],
        model: str = "dall-e-3",
        size: str = "1024x1024",
        quality: str = "standard",
        success: bool = True,
        error_message: Optional[str] = None
    ) -> None:
        """Log an image generation interaction.
        
        Args:
            prompt: The prompt sent to the image generation API.
            image_path: Path to the generated image (if successful).
            model: The image model used.
            size: Image size parameter.
            quality: Image quality parameter.
            success: Whether generation was successful.
            error_message: Error message if generation failed.
        """
        interaction = {
            "type": "image_generation",
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "parameters": {
                "size": size,
                "quality": quality
            },
            "prompt": prompt,
            "result": {
                "success": success,
                "image_path": image_path,
                "error": error_message
            }
        }
        
        self._append_interaction(interaction)

    def log_opening_panel(
        self,
        system_prompt: str,
        user_message: str,
        response: str,
        parsed_response: Optional[Dict[str, Any]] = None,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> None:
        """Log the opening panel generation (special case).
        
        Args:
            system_prompt: The system prompt sent to the LLM.
            user_message: The user message sent to the LLM.
            response: The raw response from the LLM.
            parsed_response: The parsed JSON response (if available).
            model: The LLM model used.
            temperature: Temperature parameter used.
            max_tokens: Max tokens parameter used.
        """
        interaction = {
            "type": "opening_panel",
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens
            },
            "prompt": {
                "system": system_prompt,
                "user": user_message
            },
            "response": {
                "raw": response,
                "parsed": parsed_response
            }
        }
        
        self._append_interaction(interaction)

    def _append_interaction(self, interaction: Dict[str, Any]) -> None:
        """Append an interaction to the log file.
        
        Args:
            interaction: The interaction data to append.
        """
        self.interactions.append(interaction)
        
        # Read current log
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            log_data = {
                "session_id": self.session_id,
                "start_time": datetime.now().isoformat(),
                "interactions": []
            }
        
        # Append new interaction
        log_data["interactions"].append(interaction)
        
        # Write back
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

    def get_log_path(self) -> str:
        """Get the path to the current log file.
        
        Returns:
            Absolute path to the log file.
        """
        return str(self.log_file.resolve())

    def get_interaction_count(self) -> int:
        """Get the number of interactions logged.
        
        Returns:
            Count of logged interactions.
        """
        return len(self.interactions)
