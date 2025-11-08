"""Image detection quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
import base64
import requests
from .utils import get_llm, get_user_level, get_target_language
from .cefr_utils import format_cefr_for_prompt
from tools import get_profile, get_session
from config import CONFIG

llm = get_llm()

async def generate_image_detection(session_id: str) -> Dict[str, Any]:
    """
    Generate an image detection quiz.
    Returns: {
        "object_word": "spanish word",
        "image_url": "data:image/png;base64,..." or URL,
        "difficulty": "A1|A2|B1|B2|C1|C2"
    }
    """
    session = get_session(session_id)
    
    # Get user profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level - prioritize user's stated level from profile
    quiz_results = session.get("quiz_results", [])
    current_level = get_user_level(profile, quiz_results)
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Get target language
    target_language = get_target_language(profile)
    
    # Get CEFR description for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    
    # Step 1: LLM picks a word in target language for an object
    prompt1 = f"""Select a {target_language} word for a common, recognizable object appropriate for a student at the following CEFR level:

{cefr_info}

The word should be:
- A noun (object/item)
- Common and easily recognizable
- Appropriate vocabulary for the student's level as described above
- Something that can be clearly illustrated in a simple cartoon style

Return ONLY the {target_language} word, nothing else.
Example for A1-A2 ({target_language}): [Provide {target_language} words appropriate for A1-A2 level]
Example for B1-B2 ({target_language}): [Provide {target_language} words appropriate for B1-B2 level]
Example for C1-C2 ({target_language}): [Provide {target_language} words appropriate for C1-C2 level]

Return the word now:"""

    messages1 = [
        SystemMessage(content=f"You are a {target_language} teacher selecting vocabulary words. Respond with ONLY the {target_language} word."),
        HumanMessage(content=prompt1)
    ]
    
    response1 = await llm.ainvoke(messages1)
    object_word = response1.content.strip().lower()
    
    # Clean up the word (remove any extra text)
    # Note: This regex is Spanish-specific. For other languages, we may need to adjust
    # For now, keep it flexible to handle most languages
    object_word = re.sub(r'[^\w\s]', '', object_word).strip()
    
    # Step 2: Generate image using Google Imagen (via Gemini)
    # Make the prompt very specific to match Duolingo's cartoony character style
    image_prompt = f"""A cute, friendly cartoon illustration of a {object_word} in the style of Duolingo characters. 
    
Style requirements:
- Duolingo's signature cartoony character art style
- Bright, cheerful colors (similar to Duolingo's green, blue, yellow palette)
- Rounded, friendly shapes with soft edges
- Simple, clean design with expressive features
- White or light background
- The {object_word} should be the single, main focus of the image
- Playful and approachable, like Duolingo's mascot characters
- No text, labels, or additional objects
- Centered composition

The image should look like it belongs in the Duolingo app - fun, educational, and visually appealing for language learners."""
    
    image_url = None
    image_base64 = None
    
    try:
        import google.generativeai as genai
        
        # Configure Google Generative AI
        genai.configure(api_key=CONFIG.GOOGLE_API_KEY)
        
        # Use Imagen 3 for image generation
        # The generate_images method is available in google-generativeai
        try:
            # Generate image using Imagen
            result = genai.GenerativeModel('imagen-3.0-generate-001').generate_images(
                prompt=image_prompt,
                number_of_images=1,
                aspect_ratio='1:1',
                safety_filter_level='block_some',
                person_generation='allow_all'
            )
            
            # Extract base64 image data
            if result and len(result.images) > 0:
                image_data = result.images[0]
                # If it's already base64, use it directly; otherwise convert
                if isinstance(image_data, str):
                    image_base64 = image_data
                else:
                    # Convert bytes to base64
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                    
        except (AttributeError, TypeError) as api_error:
            # Fallback: Try using REST API directly
            print(f"[Image Gen] Direct API call failed, trying REST API...")
            
            # Use Google AI Studio REST API for image generation
            api_url = "https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:generateImages"
            
            headers = {
                "Content-Type": "application/json"
            }
            
            payload = {
                "prompt": image_prompt,
                "numberOfImages": 1,
                "aspectRatio": "1:1",
                "safetyFilterLevel": "block_some",
                "personGeneration": "allow_all"
            }
            
            # Make request with API key in URL
            img_response = requests.post(
                f"{api_url}?key={CONFIG.GOOGLE_API_KEY}",
                headers=headers,
                json=payload
            )
            
            if img_response.status_code == 200:
                result = img_response.json()
                if 'generatedImages' in result and len(result['generatedImages']) > 0:
                    image_base64 = result['generatedImages'][0].get('bytesBase64Encoded')
                elif 'images' in result and len(result['images']) > 0:
                    image_base64 = result['images'][0].get('bytesBase64Encoded')
            else:
                raise Exception(f"Google API error: {img_response.status_code} - {img_response.text}")
        
    except ImportError:
        print("[Image Gen] google-generativeai not installed. Installing...")
        import subprocess
        subprocess.check_call(["pip", "install", "google-generativeai"])
        print("[Image Gen] Please restart the server and retry image generation")
    except Exception as e:
        print(f"[Image Gen Error] {e}")
        import traceback
        traceback.print_exc()
        # Fallback: return word without image, frontend can handle it
        pass
    
    return {
        "object_word": object_word,
        "image_url": image_url,
        "image_base64": image_base64,
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_image_detection(session_id: str, user_answer: str, correct_word: str) -> Dict[str, Any]:
    """Validate user's answer for image detection quiz."""
    user_answer_clean = user_answer.lower().strip()
    correct_word_clean = correct_word.lower().strip()
    
    # Exact match
    if user_answer_clean == correct_word_clean:
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "¡Correcto! Bien hecho.",
            "user_answer": user_answer
        }
    
    # Normalize (remove accents)
    def normalize(text: str) -> str:
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ñ': 'n'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.lower().strip()
    
    user_normalized = normalize(user_answer_clean)
    correct_normalized = normalize(correct_word_clean)
    
    if user_normalized == correct_normalized:
        return {
            "correct": True,
            "score": 0.95,
            "feedback": f"¡Casi perfecto! La respuesta correcta es '{correct_word}'. (Presta atención a los acentos)",
            "user_answer": user_answer
        }
    
    return {
        "correct": False,
        "score": 0.0,
        "feedback": f"La respuesta correcta es '{correct_word}'. ¡Sigue practicando!",
        "correct_answer": correct_word,
        "user_answer": user_answer
    }

