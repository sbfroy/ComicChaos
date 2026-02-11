GRAND OPENING SEQUENCE - Create an engaging two-panel opening!

COMIC: {title}
SYNOPSIS: {synopsis}
VISUAL STYLE: {visual_style}
STARTING LOCATION: {starting_location}
MAIN CHARACTER: {main_character}
{long_term_narrative_section}
{narrative_premise_section}
Create TWO panels for the grand opening:

## PANEL 1: TITLE CARD
A classic, clean title panel where the comic title dominates the frame:
- The title "{title}" must be the clear visual focus — large, prominent typography that commands the composition
- Background should be minimalist and restrained — it may subtly hint at the characters or setting, but nothing detailed or busy
- Think classic comic opening panels: title dominates, everything else is secondary
- NO speech bubbles, NO dialogue, NO detailed action or complex scenes
- Keep the composition simple and elegant — the title is the star

## PANEL 2: FIRST INTERACTIVE PANEL
The first story panel where:
- The scene is established in detail
- The main character is shown clearly
- Include exactly ONE element for user input (speech, thought, or narration)
- The story begins!

RESPOND WITH JSON:
{{
  "title_card": {{
    "scene_description": "Clean, title-dominant composition. The title '{title}' must be described as large, prominent text that dominates the frame. Background is minimal — a simple color, subtle texture, or faint silhouette. No detailed scenes or action.",
    "title_treatment": "How the title appears visually (e.g., 'Bold vintage lettering', 'Classic hand-drawn comic title', 'Large block letters')",
    "atmosphere": "The mood and feeling in 2-4 words (e.g., 'warm and inviting', 'playful and bold')"
  }},
  "first_panel": {{
    "scene_description": "Visual description for first story panel - show the main character clearly in the starting location",
    "elements": [
      {{"type": "speech|thought|narration", "character_name": "CharacterName", "position": "center (or any corner for narration)", "user_input": true, "placeholder": "What does CharacterName say/think?"}}
    ],
    "scene_summary": {{"scene_setting": "Brief setting description", "characters_present": ["Character + brief desc"], "current_action": "What's happening"}},
    "rolling_summary_update": "The story begins: brief setup of the scene"
  }},
  "initial_narrative": {{
    "short_term": ["first immediate narrative direction based on the opening scene"],
    "long_term": ["use the provided long-term narrative if given, otherwise create overarching story narrative based on the synopsis"]
  }}
}}
