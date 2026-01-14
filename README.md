# Project Description

The system is organized around a dynamic story engine that allows free player interaction while maintaining structured narrative progression. At the center is a continuously updated story state that evolves after each player's action. Think of it as a fun, new-thinking game where users can finally be the protagonist and do all the side quests they want to.

To support a comic-book-style presentation, the system extracts a purely visual summary from each updated story snapshot. This summary contains only concrete, observable elements—such as locations, characters, objects, and simple actions—and is passed to the image-generation model to ensure consistent and coherent illustrations.

The NARRATRON controls all game logic. Its role is to interpret player input, enforce rules, and maintain narrative structure.

---

## Core Control Mechanisms

### 1. Constraints
A predefined set of non-negotiable rules governs the world’s logic. These rules define what is and is not possible, regardless of player intention. Examples include:
- Specific tasks can only be completed by designated characters.
- Certain locations remain restricted or inaccessible until conditions are met.
- Physical and technological limitations must always hold.

The Narratron evaluates each player action and ensures that all responses comply with these constraints.

### 2. Checkpoints
The story contains mandatory milestones that guide the player toward the final objective. When a player action satisfies a milestone, the system triggers a checkpoint. A visual indicator (e.g., a symbol) appears in the game interface to indicate progress.

These checkpoints are enforced through backend logic, ensuring structured narrative advancement while maintaining broad creative freedom.

---

## System Flow

1. **Player Input Received**  
   The player submits an action or command.

2. **NARRATRON Processing**
   - Interprets the player's intent.
   - Validates the action against constraints.
   - Checks whether any milestones are satisfied.
   - Updates the story state accordingly.
   - Generates a clean, visual-only summary for the image generator.

3. **Image Generation**  
   The visual summary is fed to an image-generation model, which produces an illustration aligned with the updated story state.

4. **Story and UI Update**  
   The game displays the updated story text, the new comic-style image, and any checkpoint indicators.

---

## Player Experience
The player begins in a predefined environment with a clear overarching goal. While the backend defines strict constraints and milestones, the player is encouraged to attempt creative or humorous actions. Most actions will not advance the story, but they will elicit consistent and entertaining responses.

Although the player experiences freedom, only one path ultimately leads to success. NARRATRON ensures that all narrative changes remain coherent, rule-compliant, and appropriately aligned with the intended progression.

---

## The Comic State

The system distinguishes clearly between static comic logic and the dynamic comic state. This separation ensures consistency, reduces computational overhead, and allows the orchestrator module (Narratron) to reason about the story without confusion or drift.

### 1. Static Components (do not change during gameplay)

#### a. Constraints
Constraints define the permanent rules of the world. They specify what is possible, what is prohibited, and which conditions must be met for specific actions. Examples include access restrictions, required character abilities, and physical or technological limitations. These rules form the backbone of the game's logic and remain constant throughout.

#### b. Milestones
Milestones define the game's predefined narrative structure. They describe the key story beats and objectives necessary for progression. While the player may explore freely, these milestones determine the required path toward the final goal. The milestone definitions themselves are static, but the player’s progress through them is dynamic.

#### c. World Blueprint
The blueprint includes the initial layout of locations, characters, items, and environmental properties before the game begins. This serves as the foundation from which the dynamic world state evolves.

These static components are stored separately from the comic state, typically in dedicated configuration files or modules.

### 2. Dynamic Comic State (updated after every player action)
The dynamic comic state reflects the current situation in the story and changes continuously throughout gameplay. It includes:

#### a. Narrative State
A record of what has happened so far, stored as a series of short, incremental events. A rolling summary is maintained for efficient context sharing with the orchestrator.

#### b. World State
The current positions of characters and discovered locations. This is a real-time representation of the comic world driven by the player's actions.

#### c. Player State
The player’s location, inventory, attributes, and known information. This component ensures that the system responds appropriately to the player’s current situation.

#### d. Checkpoint Progress
Although milestones are defined statically, the player’s progression through them is stored dynamically. This allows the system to determine whether the player has met the conditions for advancing the story.

#### e. Render State
A distilled representation of the current scene containing only concrete, visual information. This is used to generate consistent comic-style illustrations.

#### f. Meta Information
Technical details such as timestamps, turn counters, and engine identifiers. These assist with debugging, session tracking, and reproducibility.

---

## Goal
This is a project I want to explore to push the boundaries of typical LLM use—creating a game that fully leverages this technology. The goal is not just to build an interactive narrative but also to demonstrate how large language models can orchestrate dynamic storytelling, enforce logical constraints, and generate visuals in real time. When the system is complete, my role will shift to designing puzzles and stories, ensuring that the game experience remains creative, challenging, and deeply engaging for players.

---

## Technical Requirements
- Use Python as the primary programming language for all backend logic and orchestration.
- Implement a fast image-generation model to ensure quick rendering of comic-style visuals.
- Integrate with OpenAI’s ChatGPT API for narrative orchestration. Store the API key securely using environment variables (e.g., `OPENAI_API_KEY`) rather than hardcoding it.
- Ensure modular design: separate logic for Narratron, image generation, UI rendering, and state management.
- Provide clear instructions for setting up `.env` files and loading environment variables using libraries like `python-dotenv`.

Think of it as a real life comic book where you are the protagonist and can do whatever you want. The image model and its part in the project is therfore important. It should make the story alive and therfore maybe update every 5 second or after a new user interaction.