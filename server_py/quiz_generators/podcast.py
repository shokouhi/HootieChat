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
from .utils import get_llm, get_user_level, get_target_language
from .cefr_utils import format_cefr_for_prompt, get_difficulty_guidelines
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
    # Handle both string and list formats
    if isinstance(interests, list):
        interests = ", ".join(interests) if interests else ""
    if not interests or (isinstance(interests, str) and interests.strip() == ""):
        # Use English topic names - they'll be adapted to target language by the LLM
        topics = ["sports", "food", "travel", "music", "movies", "books", "animals", "technology"]
        interests = random.choice(topics)
    
    # Get target language
    target_language = get_target_language(profile)
    
    # Get CEFR description and difficulty guidelines for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    difficulty_guide = get_difficulty_guidelines(target_level)
    
    prompt = f"""Generate a short {target_language} conversation between two people (use appropriate {target_language} names, one female and one male) for a listening comprehension exercise.

Student's CEFR Level:
{cefr_info}

DIFFICULTY GUIDELINES FOR {target_level}:
{difficulty_guide}

Requirements:
- STRICTLY MATCH the vocabulary, grammar, and sentence complexity to the guidelines above
- Topic/theme: {interests} (use this topic generally, e.g., if "tennis", write about tennis in general)
- NEVER use the student's actual name, age, or personal details in the conversation
- Use two speakers with appropriate {target_language} names (one female, one male)
- Maximum 5 sentences total for A1-A2, 7 sentences for B1+
- Natural, conversational {target_language} that EXACTLY matches the student's level
- Each sentence MUST follow the sentence structure limits in the guidelines (e.g., max 8-10 words for A1)
- Use ONLY vocabulary within the range specified for this level
- Clear dialogue with speaker labels (Speaker1:, Speaker2:)
- Output PLAIN TEXT ONLY - NO HTML, NO audio tags, NO markdown formatting

After the conversation, generate ONE comprehension question based on the conversation content. The answer should ideally be just ONE WORD in {target_language}.

Format your response EXACTLY like this (PLAIN TEXT ONLY):

CONVERSATION:
Speaker1: [first sentence]
Speaker2: [response]
Speaker1: [next sentence]
Speaker2: [response]
[Continue until max 7 sentences total]

QUESTION: [One question in {target_language} about the conversation]
ANSWER: [The correct answer, ideally one word in {target_language}]

IMPORTANT: Do NOT include any HTML tags, audio elements, or markdown. Just plain text conversation.

Generate now:"""

    messages = [
        SystemMessage(content=f"You are a {target_language} teacher creating listening comprehension exercises. Follow the format exactly."),
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
    
    # Final validation - if still missing, we cannot proceed (no language-specific fallbacks)
    if not conversation or not question or not answer:
        raise ValueError(f"[Podcast Gen] Failed to generate podcast quiz - missing required fields. Conversation: {bool(conversation)}, Question: {bool(question)}, Answer: {bool(answer)}")
    
    # Generate audio from conversation using Google TTS
    audio_url = None
    audio_base64 = None
    
    if GOOGLE_TTS_AVAILABLE:
        try:
            audio_result = await generate_audio_from_conversation(conversation, target_language)
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

async def generate_audio_from_conversation(conversation: str, target_language: str) -> Dict[str, Any]:
    """
    Generate audio from conversation using Google TTS.
    Converts "Persona A: ... Persona B: ..." format to audio.
    Returns: {"audio_url": str or None, "audio_base64": str or None}
    """
    if not GOOGLE_TTS_AVAILABLE:
        return {"audio_url": None, "audio_base64": None}
    
    try:
        # In Cloud Run, Application Default Credentials (ADC) are automatically available
        # We don't need GOOGLE_APPLICATION_CREDENTIALS file path - ADC will work
        # Try to initialize the client - it will use ADC if available
        try:
            # Test if we can create a client (will use ADC in Cloud Run)
            test_client = texttospeech.TextToSpeechClient()
            del test_client  # Clean up test client
        except Exception as e:
            # If ADC fails, check for explicit credentials file (for local dev)
            if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                print(f"[Podcast Gen] No Google credentials available (ADC or file): {e}")
                return {"audio_url": None, "audio_base64": None}
        
        # Convert conversation format: Extract speaker names and map to HOST_A/HOST_B
        # Pattern: "SpeakerName: text" -> "HOST_A: text" or "HOST_B: text"
        lines = conversation.split('\n')
        script_lines = []
        speaker_map = {}
        speaker_count = 0
        
        for line in lines:
            if ':' in line:
                speaker_name = line.split(':', 1)[0].strip()
                if speaker_name not in speaker_map:
                    if speaker_count == 0:
                        speaker_map[speaker_name] = "HOST_A"
                        speaker_count = 1
                    else:
                        speaker_map[speaker_name] = "HOST_B"
                # Replace speaker name with mapped host
                text = line.split(':', 1)[1] if ':' in line else line
                script_lines.append(f"{speaker_map[speaker_name]}:{text}")
            else:
                script_lines.append(line)
        
        script_text = '\n'.join(script_lines)
        
        # Map speakers to distinct voices based on target language
        language_code_map = {
            "Spanish": "es-ES",
            "French": "fr-FR",
            "German": "de-DE",
            "Italian": "it-IT",
            "Portuguese": "pt-PT",
            "Mandarin Chinese": "cmn-CN",
            "Hindi": "hi-IN",
            "Modern Standard Arabic": "ar-XA",
            "Bengali": "bn-IN",
            "Russian": "ru-RU",
            "Urdu": "ur-PK",  # ur-IN might not exist, use ur-PK (Pakistan)
            "English": "en-US"
        }
        lang_code = language_code_map.get(target_language, "en-US")  # Default to English if not mapped
        
        # Voice name mapping - Some languages don't support Neural2, use Standard or Wavenet instead
        # Languages known to NOT support Neural2: Arabic variants, some Asian languages
        voice_name_map = {
            # Arabic variants - use Standard voices
            "ar-XA": {
                "HOST_A": "ar-XA-Standard-A",
                "HOST_B": "ar-XA-Standard-B"
            },
            "ar-SA": {
                "HOST_A": "ar-SA-Standard-A",
                "HOST_B": "ar-SA-Standard-B"
            },
            "ar-EG": {
                "HOST_A": "ar-EG-Standard-A",
                "HOST_B": "ar-EG-Standard-B"
            },
            # Mandarin Chinese - use Wavenet (cmn-CN doesn't have Neural2-A/B format)
            "cmn-CN": {
                "HOST_A": "cmn-CN-Wavenet-A",
                "HOST_B": "cmn-CN-Wavenet-B"
            },
            # Hindi - may need Standard or Wavenet
            "hi-IN": {
                "HOST_A": "hi-IN-Wavenet-A",
                "HOST_B": "hi-IN-Wavenet-B"
            },
            # Bengali - may need Standard or Wavenet
            "bn-IN": {
                "HOST_A": "bn-IN-Standard-A",
                "HOST_B": "bn-IN-Standard-B"
            },
            # Urdu - use ur-PK (Pakistan) as ur-IN doesn't exist
            "ur-PK": {
                "HOST_A": "ur-PK-Standard-A",
                "HOST_B": "ur-PK-Standard-B"
            }
        }
        
        # Check if we have a custom voice mapping for this language
        if lang_code in voice_name_map:
            VOICE_MAP = {
                "HOST_A": {"language_code": lang_code, "name": voice_name_map[lang_code]["HOST_A"]},
                "HOST_B": {"language_code": lang_code, "name": voice_name_map[lang_code]["HOST_B"]}
            }
        else:
            # Default: try Neural2 for languages that support it (most European languages)
            VOICE_MAP = {
                "HOST_A": {"language_code": lang_code, "name": f"{lang_code}-Neural2-A"},  # Female voice
                "HOST_B": {"language_code": lang_code, "name": f"{lang_code}-Neural2-B"},  # Male voice
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
                
                try:
                    audio = client.synthesize_speech(
                        input=synthesis_input, voice=voice, audio_config=audio_cfg
                    )
                except Exception as voice_error:
                    # If Neural2 voice fails, try falling back to Standard or Wavenet
                    error_str = str(voice_error).lower()
                    if "does not exist" in error_str or "invalid" in error_str or "not found" in error_str:
                        print(f"[Podcast Gen] Voice {voice_cfg['name']} failed, trying fallback voices...")
                        # Try Standard voice as fallback
                        fallback_voice_name = voice_cfg['name'].replace("-Neural2-", "-Standard-")
                        try:
                            fallback_voice = texttospeech.VoiceSelectionParams(
                                language_code=lang_code,
                                name=fallback_voice_name,
                            )
                            audio = client.synthesize_speech(
                                input=synthesis_input,
                                voice=fallback_voice,
                                audio_config=audio_cfg
                            )
                            print(f"[Podcast Gen] ✅ Fallback to {fallback_voice_name} succeeded")
                        except Exception as fallback_error:
                            # Try Wavenet as last resort
                            wavenet_voice_name = voice_cfg['name'].replace("-Neural2-", "-Wavenet-").replace("-Standard-", "-Wavenet-")
                            try:
                                wavenet_voice = texttospeech.VoiceSelectionParams(
                                    language_code=lang_code,
                                    name=wavenet_voice_name,
                                )
                                audio = client.synthesize_speech(
                                    input=synthesis_input,
                                    voice=wavenet_voice,
                                    audio_config=audio_cfg
                                )
                                print(f"[Podcast Gen] ✅ Fallback to {wavenet_voice_name} succeeded")
                            except Exception as final_error:
                                print(f"[Podcast Gen] ❌ All voice attempts failed for {lang_code}: {final_error}")
                                raise voice_error  # Re-raise original error
                    else:
                        raise  # Re-raise if it's not a voice name error
                
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
    """Validate user's answer for podcast quiz using semantic matching."""
    from .utils import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage
    from tools import get_profile
    
    # Get target language for feedback
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
        target_language = profile.get("target_language", "English")
    except:
        target_language = "English"
    
    user_answer_clean = user_answer.strip()
    correct_answer_clean = correct_answer.strip()
    
    # First check exact match (fast path)
    if user_answer_clean.lower() == correct_answer_clean.lower():
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "Correct! Well done."
        }
    
    # Use LLM for semantic matching
    llm = get_llm()
    prompt = f"""Evaluate if the student's answer is semantically equivalent to the correct answer.

Correct answer: "{correct_answer_clean}"
Student's answer: "{user_answer_clean}"

IMPORTANT: Do not look for exact word matches. Evaluate if both answers have the same semantic meaning, even if they use different words or structures.

Examples of semantically equivalent answers:
- "Yes, I like it" and "I love it" (both express positive preference)
- "I don't know" and "I have no idea" (both express lack of knowledge)
- "That's fine" and "I agree" (both express agreement)

Respond ONLY with JSON in this exact format:
{{
    "semantically_equivalent": true/false,
    "score": 0.0-1.0,
    "reason": "brief explanation in English"
}}

If they are semantically equivalent, score must be >= 0.8. If not, score must be < 0.8."""

    messages = [
        SystemMessage(content=f"You are an answer evaluator for {target_language}. Evaluate semantic equivalence, not exact word matches."),
        HumanMessage(content=prompt)
    ]
    
    try:
        response = await llm.ainvoke(messages)
        content = response.content.strip()
        
        # Parse JSON from response
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3].strip()
        
        result = json.loads(content)
        semantically_equivalent = result.get("semantically_equivalent", False)
        score = float(result.get("score", 0.0))
        reason = result.get("reason", "")
        
        # Ensure score is in valid range
        score = max(0.0, min(1.0, score))
        
        if semantically_equivalent or score >= 0.8:
            return {
                "correct": True,
                "score": score,
                "feedback": "Correct! Well done." if score >= 0.95 else f"Good! {reason if reason else 'Answer accepted.'}"
            }
        else:
            return {
                "correct": False,
                "score": score,
                "feedback": f"The correct answer is '{correct_answer}'. {reason if reason else 'Keep practicing!'}"
            }
    except Exception as e:
        print(f"[Quiz Val] Error in semantic validation: {e}")
        # Fallback to exact match check
        if correct_answer_clean.lower() in user_answer_clean.lower() or user_answer_clean.lower() in correct_answer_clean.lower():
            return {
                "correct": False,
                "score": 0.5,
                "feedback": f"Close, but not exact. The correct answer is '{correct_answer}'."
            }
        return {
            "correct": False,
            "score": 0.0,
            "feedback": f"The correct answer is '{correct_answer}'. Keep practicing!"
        }

