"""Podcast quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
import random
import os
import tempfile
import subprocess
import shutil
import base64
from .utils import get_llm, get_user_level
from .cefr_utils import format_cefr_for_prompt
from tools import get_profile, get_session

# Google TTS imports
try:
    from google.cloud import texttospeech
    GOOGLE_TTS_AVAILABLE = True
except ImportError:
    GOOGLE_TTS_AVAILABLE = False
    print("[Podcast Gen Warning] google-cloud-texttospeech not available. Audio generation will be disabled.")

llm = get_llm()

async def generate_podcast(session_id: str) -> Dict[str, Any]:
    """
    Generate a podcast conversation and question.
    Returns: {
        "conversation": "text of conversation",
        "question": "comprehension question",
        "answer": "correct answer (one word ideal)",
        "difficulty": "A1|A2|B1|B2|C1|C2",
        "topic": "topic name"
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
    
    # Get interests or use random topic
    interests = profile.get("interests", "")
    if not interests or interests.strip() == "":
        topics = ["deportes", "comida", "viajes", "música", "películas", "libros", "animales", "tecnología"]
        interests = random.choice(topics)
    
    # Get CEFR description for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    
    prompt = f"""Generate a short Spanish conversation between two people (María (female) and Juan (male)) for a listening comprehension exercise.

Student's CEFR Level:
{cefr_info}

Requirements:
- The conversation should match the student's language abilities as described above
- Topic/theme: {interests} (use this topic generally, e.g., if "tennis", write about tennis in general)
- NEVER use the student's actual name, age, or personal details in the conversation
- Always use María (female) and Juan (male) as the speakers
- Maximum 7 sentences total (distributed between both speakers)
- Natural, conversational Spanish appropriate for the student's level
- Vocabulary and sentence structure should match the level described above
- Clear dialogue with speaker labels (María:, Juan:)
- Output PLAIN TEXT ONLY - NO HTML, NO audio tags, NO markdown formatting

After the conversation, generate ONE comprehension question based on the conversation content. The answer should ideally be just ONE WORD in Spanish.

Format your response EXACTLY like this (PLAIN TEXT ONLY):

CONVERSATION:
María: [first sentence]
Juan: [response]
María: [next sentence]
Juan: [response]
[Continue until max 7 sentences total]

QUESTION: [One question in Spanish about the conversation]
ANSWER: [The correct answer, ideally one word]

IMPORTANT: Do NOT include any HTML tags, audio elements, or markdown. Just plain text conversation.

Generate now:"""

    messages = [
        SystemMessage(content="You are a Spanish teacher creating listening comprehension exercises. Follow the format exactly."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content
    
    # Log the raw response for debugging
    print(f"[Podcast Gen] Raw LLM response (first 500 chars): {content[:500]}")
    
    # Parse conversation and question/answer
    conversation = ""
    question = ""
    answer = ""
    
    # Extract conversation - try multiple patterns
    conv_match = re.search(r'CONVERSATION:\s*(.*?)(?=QUESTION:|$)', content, re.DOTALL | re.IGNORECASE)
    if not conv_match:
        # Try without the label, look for Persona A/B pattern
        conv_match = re.search(r'(Persona\s+A:.*?)(?=QUESTION:|$)', content, re.DOTALL | re.IGNORECASE)
    
    if conv_match:
        conversation = conv_match.group(1).strip()
        # Clean up any trailing ANSWER or QUESTION labels that might have been captured
        conversation = re.sub(r'\s*(QUESTION|ANSWER):.*$', '', conversation, flags=re.IGNORECASE)
        # Strip any HTML tags (including audio tags) that LLM might have added
        conversation = re.sub(r'<[^>]+>', '', conversation)
    else:
        # Fallback: try to extract everything before QUESTION as conversation
        q_pos = content.find('QUESTION:')
        if q_pos > 0:
            conversation = content[:q_pos].strip()
            # Remove CONVERSATION: label if present
            conversation = re.sub(r'^CONVERSATION:\s*', '', conversation, flags=re.IGNORECASE)
            # Strip any HTML tags
            conversation = re.sub(r'<[^>]+>', '', conversation)
    
    # Extract question
    q_match = re.search(r'QUESTION:\s*(.+?)(?=ANSWER:|$)', content, re.DOTALL | re.IGNORECASE)
    if not q_match:
        # Try alternative pattern
        q_match = re.search(r'PREGUNTA:\s*(.+?)(?=RESPUESTA:|ANSWER:|$)', content, re.DOTALL | re.IGNORECASE)
    
    if q_match:
        question = q_match.group(1).strip()
        # Clean up any trailing ANSWER label
        question = re.sub(r'\s*ANSWER:.*$', '', question, flags=re.IGNORECASE)
        # Strip any HTML tags
        question = re.sub(r'<[^>]+>', '', question)
    
    # Extract answer
    a_match = re.search(r'ANSWER:\s*(.+?)(?:\n\n|\n$|$)', content, re.DOTALL | re.IGNORECASE)
    if not a_match:
        # Try alternative pattern
        a_match = re.search(r'RESPUESTA:\s*(.+?)(?:\n\n|\n$|$)', content, re.DOTALL | re.IGNORECASE)
    
    if a_match:
        answer = a_match.group(1).strip()
        # Clean answer - get first word if multiple words
        answer_words = answer.split()
        if len(answer_words) > 1:
            # Try to find the key word (take first word, or if answer contains quotes, extract that)
            if '"' in answer or "'" in answer:
                # Extract quoted word if present
                quoted_match = re.search(r'["\']([^"\']+)["\']', answer)
                if quoted_match:
                    answer = quoted_match.group(1).strip()
                else:
                    answer = answer_words[0]
            else:
                answer = answer_words[0]
        else:
            answer = answer_words[0] if answer_words else ""
    
    # If any field is missing, log the full content for debugging
    if not conversation or not question or not answer:
        print(f"[Podcast Gen Warning] Missing fields - conversation: {bool(conversation)}, question: {bool(question)}, answer: {bool(answer)}")
        print(f"[Podcast Gen] Full content:\n{content}")
        
        # Try more lenient parsing as fallback
        if not conversation:
            # Extract any dialogue-like content
            lines = content.split('\n')
            conv_lines = []
            for line in lines:
                if 'Persona' in line or ':' in line and not line.startswith('QUESTION') and not line.startswith('ANSWER'):
                    conv_lines.append(line.strip())
            if conv_lines:
                conversation = '\n'.join(conv_lines[:7])  # Max 7 sentences
                # Strip any HTML tags
                conversation = re.sub(r'<[^>]+>', '', conversation)
        
        if not question:
            # Look for any question mark
            q_match = re.search(r'([^?\n]+[?])', content)
            if q_match:
                question = q_match.group(1).strip()
        
        if not answer:
            # Look for single word after ANSWER
            words_after_answer = re.findall(r'ANSWER[:\s]+(\w+)', content, re.IGNORECASE)
            if words_after_answer:
                answer = words_after_answer[0]
    
    # Final validation - if still missing, provide defaults
    if not conversation:
        conversation = "María: Hola. ¿Cómo estás?\nJuan: Bien, gracias. ¿Y tú?"
        print("[Podcast Gen] Using fallback conversation")
    
    if not question:
        question = "¿Qué dijo Juan?"
        print("[Podcast Gen] Using fallback question")
    
    if not answer:
        answer = "bien"
        print("[Podcast Gen] Using fallback answer")
    
    # Generate audio from conversation using Google TTS
    audio_url = None
    audio_base64 = None
    
    if GOOGLE_TTS_AVAILABLE:
        try:
            audio_result = await generate_audio_from_conversation(conversation)
            audio_url = audio_result.get("audio_url")
            audio_base64 = audio_result.get("audio_base64")
        except Exception as e:
            print(f"[Podcast Gen] Audio generation failed: {e}")
            # Continue without audio - text will still be available
    
    return {
        "conversation": conversation,
        "question": question,
        "answer": answer.lower().strip(),
        "difficulty": target_level,
        "original_level": current_level,
        "topic": interests,
        "audio_url": audio_url,
        "audio_base64": audio_base64
    }

async def generate_audio_from_conversation(conversation: str) -> Dict[str, Any]:
    """
    Generate audio from conversation using Google TTS.
    Converts "Persona A: ... Persona B: ..." format to audio.
    Returns: {"audio_url": str or None, "audio_base64": str or None}
    """
    if not GOOGLE_TTS_AVAILABLE:
        return {"audio_url": None, "audio_base64": None}
    
    try:
        # Check for Google credentials
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            print("[Podcast Gen] GOOGLE_APPLICATION_CREDENTIALS not set, skipping audio generation")
            return {"audio_url": None, "audio_base64": None}
        
        # Convert conversation format: "María: text" -> "HOST_A: text", "Juan: text" -> "HOST_B: text"
        script_text = conversation.replace("María:", "HOST_A:").replace("Juan:", "HOST_B:")
        
        # Map speakers to distinct Spanish voices
        VOICE_MAP = {
            "HOST_A": {"language_code": "es-ES", "name": "es-ES-Neural2-A"},  # Female Spanish voice
            "HOST_B": {"language_code": "es-ES", "name": "es-ES-Neural2-B"},  # Male Spanish voice
        }
        
        def to_ssml(text: str) -> str:
            """Convert text to SSML format."""
            text = text.replace("<pause/>", '<break time="400ms"/>')
            return f"<speak>{text}</speak>"
        
        # Split by speaker turns
        turns = []
        for line in script_text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Match "HOST_X: text" pattern
            m = re.match(r"^(HOST_[A-Z]+):\s*(.+)$", line)
            if m:
                speaker, utterance = m.group(1), m.group(2)
                turns.append((speaker, utterance))
        
        if not turns:
            print("[Podcast Gen] No valid speaker turns found in conversation")
            return {"audio_url": None, "audio_base64": None}
        
        # Initialize TTS client
        client = texttospeech.TextToSpeechClient()
        temp_files = []
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Synthesize each turn
            for i, (speaker, utterance) in enumerate(turns, 1):
                voice_cfg = VOICE_MAP.get(speaker, VOICE_MAP["HOST_A"])
                
                synthesis_input = texttospeech.SynthesisInput(ssml=to_ssml(utterance))
                
                voice = texttospeech.VoiceSelectionParams(
                    language_code=voice_cfg["language_code"],
                    name=voice_cfg["name"],
                )
                audio_cfg = texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3,
                    speaking_rate=1.0,
                    pitch=0.0,
                )
                
                audio = client.synthesize_speech(
                    input=synthesis_input, voice=voice, audio_config=audio_cfg
                )
                
                # Write temp file
                tmpfile = os.path.join(tmpdir, f"turn_{i}.mp3")
                with open(tmpfile, "wb") as f:
                    f.write(audio.audio_content)
                temp_files.append(tmpfile)
            
            # Concatenate using ffmpeg
            concat_file = os.path.join(tmpdir, "concat_list.txt")
            with open(concat_file, "w") as f:
                for tf in temp_files:
                    # Use forward slashes for ffmpeg even on Windows
                    f.write(f"file '{tf.replace(chr(92), '/')}'\n")
            
            # Find ffmpeg
            ffmpeg_path = shutil.which("ffmpeg")
            if not ffmpeg_path:
                # Try common winget installation path
                winget_base = os.path.join(os.environ.get("LOCALAPPDATA", ""), 
                                           "Microsoft", "WinGet", "Packages")
                if os.path.exists(winget_base):
                    for item in os.listdir(winget_base):
                        if "FFmpeg" in item:
                            ffmpeg_dir = os.path.join(winget_base, item)
                            for subdir in os.listdir(ffmpeg_dir):
                                if subdir.startswith("ffmpeg-") and subdir.endswith("-full_build"):
                                    bin_path = os.path.join(ffmpeg_dir, subdir, "bin", "ffmpeg.exe")
                                    if os.path.exists(bin_path):
                                        ffmpeg_path = bin_path
                                        break
                            if ffmpeg_path:
                                break
            
            if not ffmpeg_path:
                print("[Podcast Gen] ffmpeg not found, cannot concatenate audio")
                # Return first file as fallback if only one turn
                if len(temp_files) == 1:
                    with open(temp_files[0], "rb") as f:
                        audio_data = f.read()
                    return {
                        "audio_url": None,
                        "audio_base64": base64.b64encode(audio_data).decode('utf-8')
                    }
                return {"audio_url": None, "audio_base64": None}
            
            # Concatenate audio files
            output_file = os.path.join(tmpdir, "podcast_audio.mp3")
            subprocess.run([
                ffmpeg_path, "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                "-y",
                output_file
            ], check=True, capture_output=True, text=True)
            
            # Read the concatenated audio file
            with open(output_file, "rb") as f:
                audio_data = f.read()
            
            # Convert to base64 for embedding
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            print(f"[Podcast Gen] ✅ Generated audio: {len(audio_data)} bytes, {len(turns)} turns")
            
            return {
                "audio_url": None,  # Could be saved to a public URL in production
                "audio_base64": audio_base64
            }
    
    except Exception as e:
        print(f"[Podcast Gen] Audio generation error: {e}")
        import traceback
        traceback.print_exc()
        return {"audio_url": None, "audio_base64": None}

async def validate_podcast(session_id: str, user_answer: str, correct_answer: str) -> Dict[str, Any]:
    """Validate user's answer for podcast quiz."""
    user_answer_clean = user_answer.lower().strip()
    correct_answer_clean = correct_answer.lower().strip()
    
    # Exact match
    if user_answer_clean == correct_answer_clean:
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "¡Correcto! Bien hecho."
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
    correct_normalized = normalize(correct_answer_clean)
    
    if user_normalized == correct_normalized:
        return {
            "correct": True,
            "score": 0.95,
            "feedback": f"¡Casi perfecto! La respuesta correcta es '{correct_answer}'. (Presta atención a los acentos)"
        }
    
    # Partial match (answer contains the word or vice versa)
    if correct_answer_clean in user_answer_clean or user_answer_clean in correct_answer_clean:
        return {
            "correct": False,
            "score": 0.5,
            "feedback": f"Cerca, pero no exacto. La respuesta correcta es '{correct_answer}'."
        }
    
    return {
        "correct": False,
        "score": 0.0,
        "feedback": f"La respuesta correcta es '{correct_answer}'. ¡Sigue practicando!"
    }

