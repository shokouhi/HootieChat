"""CEFR level descriptions and utilities."""
import os
from typing import Dict, Optional

# CEFR level descriptions (loaded from file or defined here)
CEFR_DESCRIPTIONS: Dict[str, str] = {}

def load_cefr_descriptions() -> Dict[str, str]:
    """Load CEFR level descriptions from file."""
    global CEFR_DESCRIPTIONS
    
    if CEFR_DESCRIPTIONS:
        return CEFR_DESCRIPTIONS
    
    # Try to read from the file (path relative to server_py)
    file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "public", "cefr_levels.txt")
    
    if not os.path.exists(file_path):
        # Fallback: use hardcoded descriptions
        return get_fallback_descriptions()
    
    current_level = None
    description_lines = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                # Empty line - save previous level and reset
                if current_level and description_lines:
                    CEFR_DESCRIPTIONS[current_level] = "\n".join(description_lines)
                    description_lines = []
                    current_level = None
                continue
            
            # Check if this line starts a new level (e.g., "A1 (Breakthrough)" or "A1 )Breakthrough)")
            # Pattern: starts with letter followed by digit (A1, A2, B1, etc.)
            if len(line) >= 2 and line[0].isupper() and line[1].isdigit():
                # Save previous level if exists
                if current_level and description_lines:
                    CEFR_DESCRIPTIONS[current_level] = "\n".join(description_lines)
                
                # Extract level code (A1, A2, B1, etc.) - first two characters
                # Handle formats like "A1 )Breakthrough)" or "A1 (Breakthrough)"
                level_match = line[:2]  # A1, A2, B1, etc.
                if level_match in ["A1", "A2", "B1", "B2", "C1", "C2"]:
                    current_level = level_match
                    description_lines = []
            elif current_level:
                # This is a description line for current level (starts with "- ")
                if line.startswith("- "):
                    description_lines.append(line)
                elif description_lines:
                    # Continue previous line if it doesn't start with "-"
                    description_lines[-1] += " " + line
    
    if not CEFR_DESCRIPTIONS:
        return get_fallback_descriptions()
    
    return CEFR_DESCRIPTIONS

def get_fallback_descriptions() -> Dict[str, str]:
    """Fallback CEFR descriptions if file not found."""
    return {
        "A1": "Can understand and use familiar everyday expressions and very basic phrases aimed at the satisfaction of needs of a concrete type. Can introduce themselves to others and can ask and answer questions about personal details such as where they live, people they know and things they have. Can interact in a simple way provided the other person talks slowly and clearly and is prepared to help.",
        "A2": "Can understand sentences and frequently used expressions related to areas of most immediate relevance (e.g. very basic personal and family information, shopping, local geography, employment). Can communicate in simple and routine tasks requiring a simple and direct exchange of information on familiar and routine matters. Can describe in simple terms aspects of their background, immediate environment and matters in areas of immediate need.",
        "B1": "Can understand the main points of clear standard input on familiar matters regularly encountered in work, school, leisure, etc. Can deal with most situations likely to arise while travelling in an area where the language is spoken. Can produce simple connected text on topics that are familiar or of personal interest. Can describe experiences and events, dreams, hopes and ambitions and briefly give reasons and explanations for opinions and plans.",
        "B2": "Can understand the main ideas of complex text on both concrete and abstract topics, including technical discussions in their field of specialisation. Can interact with a degree of fluency and spontaneity that makes regular interaction with native speakers quite possible without strain for either party. Can produce clear, detailed text on a wide range of subjects and explain a viewpoint on a topical issue giving the advantages and disadvantages of various options.",
        "C1": "Can understand a wide range of demanding, longer clauses and recognise implicit meaning. Can express ideas fluently and spontaneously without much obvious searching for expressions. Can use language flexibly and effectively for social, academic and professional purposes. Can produce clear, well-structured, detailed text on complex subjects, showing controlled use of organisational patterns, connectors and cohesive devices.",
        "C2": "Can understand with ease virtually everything heard or read. Can summarise information from different spoken and written sources, reconstructing arguments and accounts in a coherent presentation. Can express themselves spontaneously, very fluently and precisely, differentiating finer shades of meaning even in the most complex situations."
    }

def get_cefr_description(level: str) -> str:
    """
    Get CEFR description for a given level.
    Supports single levels (A1, A2, etc.) and range levels (A1-A2, B1-B2, etc.)
    """
    descriptions = load_cefr_descriptions()
    
    # Handle range levels (e.g., "A1-A2")
    if "-" in level:
        parts = level.split("-")
        if len(parts) == 2:
            # Return description for the higher level in the range
            higher_level = parts[1].strip()
            return descriptions.get(higher_level, descriptions.get("A1", ""))
    
    # Single level
    return descriptions.get(level.upper(), descriptions.get("A1", ""))

def format_cefr_for_prompt(level: str) -> str:
    """
    Format CEFR level and description for use in LLM prompts.
    Returns a formatted string like:
    "A1 (Breakthrough): Can understand and use familiar everyday expressions..."
    """
    description = get_cefr_description(level)
    level_name = level.upper()
    
    # Add level name/title
    level_names = {
        "A1": "Breakthrough",
        "A2": "Waystage",
        "B1": "Threshold",
        "B2": "Vantage",
        "C1": "Advanced",
        "C2": "Mastery"
    }
    
    # Handle range levels
    if "-" in level:
        parts = level.split("-")
        if len(parts) == 2:
            level_name = f"{parts[0].upper()}-{parts[1].upper()}"
            # Use the higher level's name
            higher = parts[1].strip().upper()
            title = level_names.get(higher, "")
        else:
            title = ""
    else:
        title = level_names.get(level_name, "")
    
    if title:
        return f"{level_name} ({title}): {description}"
    else:
        return f"{level_name}: {description}"

