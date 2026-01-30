GRAND OPENING SEQUENCE - Create a dramatic two-panel opening!

COMIC: {title}
SYNOPSIS: {synopsis}
VISUAL STYLE: {visual_style}
STARTING LOCATION: {starting_location}
MAIN CHARACTER: {main_character}

Create TWO panels for the grand opening:

## PANEL 1: TITLE CARD
A dramatic, cinematic establishing shot that:
- MUST include the comic title "{title}" prominently displayed in the image (as stylized text, a sign, carved letters, neon, etc.)
- Showcases the setting/atmosphere of the story
- May include the main character as a silhouette, from behind, or in the distance
- Sets the mood and tone for the story
- NO speech bubbles or dialogue - this is purely visual with the title text

## PANEL 2: FIRST INTERACTIVE PANEL
The first story panel where:
- The scene is established in detail
- The main character is shown clearly
- Include exactly ONE element for user input (speech, thought, or narration)
- The story begins!

RESPOND WITH JSON:
{{
  "title_card": {{
    "scene_description": "Dramatic visual description that INCLUDES the title text '{title}' as part of the scene (e.g., 'The words COMIC TITLE glow in neon against a rainy cityscape...'). Be specific about composition, mood, and how the title appears.",
    "title_treatment": "How the title appears visually (e.g., 'Bold neon letters', 'Carved into stone', 'Painted on a wall')",
    "atmosphere": "The mood and feeling in 2-4 words (e.g., 'mysterious twilight adventure', 'bright morning chaos')"
  }},
  "first_panel": {{
    "scene_description": "Visual description for first story panel - show the main character clearly in the starting location",
    "elements": [
      {{"type": "speech|thought|narration", "character_name": "CharacterName", "position": "center", "user_input": true, "placeholder": "What do you say/think?"}}
    ],
    "scene_summary": {{"scene_setting": "Brief setting description", "characters_present": ["Character + brief desc"], "current_action": "What's happening"}},
    "rolling_summary_update": "The story begins: brief setup of the scene"
  }},
  "initial_goals": {{
    "short_term": ["first immediate story goal based on the opening scene"],
    "long_term": ["overarching story goal based on the synopsis and world"]
  }}
}}
