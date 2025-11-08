from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from config import CONFIG
from prompts import SYSTEM_PROMPT, FIRST_TURN_PROMPT, CEFR_RUBRIC, CORRECTION_POLICY, LESSON_PLANNER, QUIZ_CEFR_ASSESSMENT, QUIZ_PERFORMANCE_SCORER
from tools import get_profile, save_assessment, get_session
import json

# Supported languages
SUPPORTED_LANGUAGES = {
    "english": "English",
    "mandarin chinese": "Mandarin Chinese",
    "chinese": "Mandarin Chinese",
    "mandarin": "Mandarin Chinese",
    "hindi": "Hindi",
    "spanish": "Spanish",
    "french": "French",
    "modern standard arabic": "Modern Standard Arabic",
    "arabic": "Modern Standard Arabic",
    "msa": "Modern Standard Arabic",
    "bengali": "Bengali",
    "portuguese": "Portuguese",
    "russian": "Russian",
    "urdu": "Urdu"
}

SUPPORTED_LANGUAGES_LIST = [
    "English",
    "Mandarin Chinese",
    "Hindi",
    "Spanish",
    "French",
    "Modern Standard Arabic",
    "Bengali",
    "Portuguese",
    "Russian",
    "Urdu"
]

def normalize_language(language: str) -> str:
    """Normalize language name to supported format."""
    if not language:
        return None
    lang_lower = language.lower().strip()
    return SUPPORTED_LANGUAGES.get(lang_lower, None)

def is_language_supported(language: str) -> bool:
    """Check if a language is supported."""
    return normalize_language(language) is not None

def get_llm():
    """Initialize LLM based on provider configuration."""
    if CONFIG.PROVIDER == "google":
        return ChatGoogleGenerativeAI(
            model=CONFIG.GOOGLE_MODEL,
            temperature=0.7,
            google_api_key=CONFIG.GOOGLE_API_KEY
        )
    else:
        return ChatOpenAI(
            model=CONFIG.OPENAI_MODEL,
            temperature=0.7,
            openai_api_key=CONFIG.OPENAI_API_KEY
        )

llm = get_llm()

# Tool bindings for agent
from tools import upsert_profile, get_profile, save_assessment, save_quiz_result
import random

tools = [upsert_profile, get_profile, save_assessment, save_quiz_result]

# Test type definitions
TEST_TYPES = [
    "image_detection",      # (1) Image detection/recognition
    "unit_completion",      # (2) Unit completion tasks
    "keyword_match",        # (3) Rapid review keyword match
    "pronunciation",        # (4) Pronunciation
    "podcast",              # (5) Podcast listening
    "reading"               # (6) Reading comprehension
]

# Bind tools to LLM
llm_with_tools = llm.bind_tools(tools)

# 1) CEFR Assessment → JSON
assess_prompt = ChatPromptTemplate.from_messages([
    ("system", CEFR_RUBRIC),
    ("human", "Evaluate this message per CEFR rubric.\n\nUser:\n{last_user}\n\nRubric:\n{cefr_rubric}")
])

assess_chain = assess_prompt | llm | StrOutputParser()

# 2) Correction policy → JSON
correct_prompt = ChatPromptTemplate.from_messages([
    ("system", CORRECTION_POLICY),
    ("human", "Apply the correction policy and return JSON.\n\nUser:\n{last_user}\n\nPolicy:\n{correction_policy}")
])

correct_chain = correct_prompt | llm | StrOutputParser()

# Quiz-based CEFR assessment → JSON
quiz_assess_prompt = ChatPromptTemplate.from_messages([
    ("system", QUIZ_CEFR_ASSESSMENT),
    ("human", "Evaluate this user's overall language proficiency in their target language based on ALL their quiz results:\n\n{quiz_results_summary}\n\nRubric:\n{quiz_cefr_assessment}")
])

quiz_assess_chain = quiz_assess_prompt | llm | StrOutputParser()

# Quiz performance scorer → JSON (0-100 score)
quiz_scorer_prompt = ChatPromptTemplate.from_messages([
    ("system", QUIZ_PERFORMANCE_SCORER),
    ("human", "Quiz Type: {test_type}\nStudent's Response: {user_input}\nExpected Answer/Criteria: {expected_info}\nRaw Metrics (if applicable): {raw_metrics}\nDifficulty Level: {difficulty_level}")
])

quiz_scorer_chain = quiz_scorer_prompt | llm | StrOutputParser()

# User intent detection → JSON
intent_detection_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are analyzing user messages to understand their intent. Return JSON with:
- is_help_request: boolean (true if user is asking for help, clarification, or doesn't understand something)
- is_language_question: boolean (true if user is asking about language, translation, grammar, vocabulary, etc.)
- requested_test_type: string or null (one of: "unit_completion", "keyword_match", "pronunciation", "podcast", "reading", "image_detection" if user explicitly requests a specific test type)
- test_type_preferences: object with test types as keys and preference weights (0-5) as values

Understand natural language - users may express preferences in various ways like "I like image tests", "more vocabulary", "can we do pronunciation", etc."""),
    ("human", "User message: {user_message}\n\nReturn JSON: {{\"is_help_request\": bool, \"is_language_question\": bool, \"requested_test_type\": \"string or null\", \"test_type_preferences\": {{\"unit_completion\": 0, \"keyword_match\": 0, \"pronunciation\": 0, \"podcast\": 0, \"reading\": 0, \"image_detection\": 0}}}}")
])

intent_detection_chain = intent_detection_prompt | llm | StrOutputParser()

# 3) Lesson planner → JSON
async def lesson_plan_func(input_dict: Dict[str, Any]) -> str:
    """Plan lesson with profile and assessment."""
    profile = await get_profile.ainvoke({"session_id": input_dict["session_id"]})
    assessment_str = input_dict["assessment_json"] if isinstance(input_dict["assessment_json"], str) else json.dumps(input_dict["assessment_json"])
    
    prompt = f"""You are planning the next micro-lesson.
User Profile JSON:
{profile}

Latest Assessment JSON:
{assessment_str}

Return JSON per spec:
{LESSON_PLANNER}"""
    
    messages = [
        SystemMessage(content="You are planning the next micro-lesson."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    return response.content

# 4) Final tutor reply with function calling
async def tutor_reply(input_dict: Dict[str, Any], missing_info: list = None, is_language_question: bool = False) -> str:
    """Generate tutor reply using agentic function calling."""
    session = get_session(input_dict["session_id"])
    history = [
        HumanMessage(content=m["content"]) if m["role"] == "user" 
        else AIMessage(content=m["content"])
        for m in session.get("history", [])
    ]
    
    # Check if this is the first turn (passed from run_step)
    is_first_turn = input_dict.get("is_first_turn", False)
    
    # Check if user is asking for help in English - use LLM to understand intent
    # This will be determined by the LLM's response and context, not keyword matching
    needs_help = False  # Will be determined by LLM based on conversation context
    
    # Get selected test type for this turn (skip for first turn)
    selected_test_type = input_dict.get("test_type", None)
    
    # Use appropriate prompt
    if is_first_turn:
        # First turn: English prompt to collect info
        from prompts import FIRST_TURN_PROMPT
        system_prompt = FIRST_TURN_PROMPT
        instruction = """Welcome the user and explain how the app works. Ask them to share:
- What language they want to learn (MOST IMPORTANT - quizzes won't start until this is specified)
- Their name
- Their age (or age range)
- Their interests/hobbies
- Their current level in that language

Keep it warm and encouraging!"""
    else:
        # Subsequent turns: Spanish prompt with test integration
        system_prompt = SYSTEM_PROMPT
        
        # Get quiz feedback and assessment info
        last_quiz_result = input_dict.get("last_quiz_result")
        quiz_based_assessment = input_dict.get("quiz_based_assessment")
        
        quiz_feedback_section = ""
        if last_quiz_result:
            # Use LLM-generated score if available, otherwise fall back to raw score
            score_percent = last_quiz_result.get("llm_score_percent", last_quiz_result.get("score", 0) * 100)
            quiz_feedback_section = f"""
            
            The student just completed a test (type: {last_quiz_result.get('test_type', 'unknown')}).
            Score: {score_percent:.0f}% (use internally, don't mention the number to user).
            
            Provide brief, appropriate feedback (1 sentence max, super casual):
            - If score >= 80%: "¡Bien hecho!" or "¡Excelente!"
            - If score 60-79%: Brief neutral acknowledgment like "Bien" or "Sigue así"
            - If score < 60%: Brief supportive acknowledgment like "No te preocupes, seguimos practicando" or "Sigue intentando"
            
            CRITICAL: Match your tone to their actual performance:
            - If they scored poorly (< 60%), be supportive but NOT enthusiastic or fake-positive
            - If they scored medium (60-79%), be neutral and encouraging
            - Only be enthusiastic if they scored well (>= 80%)
            - Never say things like "¡Vamos! 😊" or "¡Muy bien!" if they scored below 60% - that's fake positivity
            Keep it brief and appropriate to their performance - don't be overly enthusiastic if they struggled."""

        assessment_section = ""
        if quiz_based_assessment:
            level = quiz_based_assessment.get("level", "A1")
            recommendations = quiz_based_assessment.get("recommendations", "")
            
            # Use assessment internally but don't tell the user
            assessment_section = f"""
            
            Internal assessment (use to adjust your language complexity to match their target language, but DON'T mention levels/scores to user):
            - Estimated level: {level} (adjust your language complexity to match)
            - Recommendations: {recommendations}
            
            Adjust difficulty naturally - teach at their level without mentioning it."""
        
        test_instruction = ""
        if selected_test_type:
            test_instructions = {
                "unit_completion": "A sentence completion exercise is coming. DO NOT include the actual sentence or multiple choice options in your message - just briefly introduce that it's a completion exercise. The quiz container will show the sentence.",
                "keyword_match": "A vocabulary matching exercise is coming. DO NOT include the actual words or matching pairs in your message - just briefly introduce that it's a matching exercise. The quiz container will show the words.",
                "pronunciation": "A pronunciation practice is coming. DO NOT include the actual sentence or phrase to pronounce - just briefly introduce that it's a pronunciation practice. The quiz container will show the sentence.",
                "podcast": "A listening comprehension task is coming. DO NOT include the conversation text or question in your message - just briefly introduce that it's a listening exercise. The quiz container will show the audio and questions.",
                "reading": "A reading comprehension task is coming. DO NOT include the article text or questions in your message - just briefly introduce that it's a reading exercise. The quiz container will show the text and questions.",
                "image_detection": "An image recognition exercise is coming. DO NOT reveal what the object is or give hints - just say 'Look at this image' or 'What do you see?' The quiz container will show the image."
            }
            test_instruction = f"\nTEST TYPE: {selected_test_type.upper()}\n{test_instructions.get(selected_test_type, 'Include an appropriate test task personalized to their interests.')}"
        
        # Get user profile for personalization
        profile_str = await get_profile.ainvoke({"session_id": input_dict["session_id"]})
        try:
            profile = json.loads(profile_str)
        except:
            profile = {}
        
        session_id = input_dict["session_id"]
        profile_info = ""
        if profile:
            profile_parts = []
            if profile.get("name"):
                profile_parts.append(f"Name: {profile.get('name')}")
            if profile.get("age"):
                profile_parts.append(f"Age: {profile.get('age')}")
            if profile.get("interests"):
                profile_parts.append(f"Interests: {profile.get('interests')}")
            # Include target language and level for internal use
            target_language = profile.get("target_language")  # None if not set (defaults to English)
            stated_level = profile.get("language_level") or profile.get("spanish_level")  # Support both for backward compatibility
            if target_language:
                profile_parts.append(f"Target Language: {target_language}")
            if stated_level:
                profile_parts.append(f"Stated Language Level: {stated_level} (use this as base for content difficulty)")
            if profile_parts:
                profile_info = f"\n\nUser Profile:\n{', '.join(profile_parts)}"
        
        # Always include session_id in profile_info (even if profile is empty)
        profile_info += f"\n- Session ID: {session_id}\n\nCRITICAL: When calling the upsert_profile tool, you MUST use session_id: '{session_id}'. Do NOT use any other session_id value like '123' or example values."
        
        language_note = ""
        if needs_help:
            target_lang = profile.get("target_language") if profile else None
            if target_lang:
                language_note = f"\n\nNOTE: User asked for help in English. You may respond briefly in English to clarify, then continue in {target_lang}."
            else:
                language_note = "\n\nNOTE: User asked for help. Respond in English (target language not yet set)."
        
        # Determine instruction based on context
        # Get target language from profile - default to English if not set
        target_language = profile.get("target_language") if profile else None
        if not target_language:
            target_language = "English"  # Default to English until user specifies
        
        # Get session_id for tool calls
        session_id = input_dict["session_id"]
        
        # Add missing info prompt if needed (passed from run_step)
        missing_info_list = input_dict.get("missing_info", [])
        is_lang_question = input_dict.get("is_language_question", False)
        missing_info_prompt = ""
        if missing_info_list and not is_lang_question:
            # Get current profile to check target_language
            profile_str = await get_profile.ainvoke({"session_id": input_dict["session_id"]})
            try:
                current_profile = json.loads(profile_str)
            except:
                current_profile = {}
            
            missing_items = []
            # Prioritize target_language - it's critical for starting quizzes
            if "target_language" in missing_info_list:
                missing_items.append("what language they want to learn")
            if "name" in missing_info_list:
                missing_items.append("their name")
            if "age" in missing_info_list:
                missing_items.append("their age")
            if "interests" in missing_info_list:
                missing_items.append("their interests/hobbies")
            if "language_level" in missing_info_list and current_profile.get("target_language"):
                missing_items.append(f"their current level in {current_profile.get('target_language')}")
            
            if missing_items:
                # Check if user's current message might contain the missing info (they might have just provided it)
                user_message = input_dict.get("last_user", "").lower()
                # If target_language is missing, emphasize it strongly
                if "target_language" in missing_info_list:
                    # Check if user might have mentioned a language in their message
                    language_mentioned = any(lang in user_message for lang in ["spanish", "french", "german", "italian", "portuguese", "chinese", "japanese", "korean", "arabic", "hindi", "russian", "farsi", "persian"])
                    if language_mentioned:
                        missing_info_prompt = f"\n\nIMPORTANT: The user may have just mentioned their target language in their message. Extract and save it using the upsert_profile tool immediately. DO NOT ask for it again - just save what they provided and proceed."
                    else:
                        missing_info_prompt = f"\n\nCRITICAL: The user hasn't specified what language they want to learn. You MUST ask about their language preference before starting any quizzes. Be friendly and casual, but make it clear that you need to know which language they want to learn. You can continue chatting, but keep gently probing about their language preference until they provide it.\n\nREMEMBER: When the user provides their language preference (or any other profile information), you MUST immediately use the upsert_profile tool to save it."
                else:
                    missing_info_prompt = f"\n\nIMPORTANT: The user hasn't provided: {', '.join(missing_items)}. However, check their current message carefully - they may have just provided this information. If so, extract and save it using the upsert_profile tool immediately. If not, gently ask about ONE of these missing pieces of information in your response. Keep it casual and brief.\n\nREMEMBER: When the user provides any of this information, you MUST immediately use the upsert_profile tool to save it."
        
        # Add language question handling
        language_question_prompt = ""
        if is_lang_question:
            profile_str = await get_profile.ainvoke({"session_id": input_dict["session_id"]})
            try:
                profile = json.loads(profile_str)
            except:
                profile = {}
            target_lang = profile.get("target_language", "the target language")
            language_question_prompt = f"\n\nIMPORTANT: The user is asking a language-related question. Answer their question helpfully and provide related information/translations about {target_lang}. Use this as a teaching opportunity. After answering, you can continue with a quiz if appropriate."
        
        if last_quiz_result:
            # User just completed a quiz - provide brief feedback ONLY (no transition - that happens separately)
            instruction = f"""You are Hootie. The student just completed a quiz. Provide VERY BRIEF feedback (1 sentence max) in {target_language}:{profile_info}

{quiz_feedback_section}
{assessment_section}

IMPORTANT: This is ONLY the feedback message. Do NOT transition to the next quiz or say anything about what's coming next. Just give the feedback and stop."""
        elif selected_test_type:
            # New turn starting with a quiz
            instruction = f"""You are Hootie. A new lesson turn is starting. NO GREETINGS - just briefly introduce the quiz naturally in {target_language}:{profile_info}
{missing_info_prompt}
{language_question_prompt}

{test_instruction}
{assessment_section}

Style:
- Maximum 1 sentence total
- Brief and casual like Duolingo
- NO greetings or saying their name (we're already in conversation)
- Just introduce that a quiz/exercise is coming - DO NOT include the actual quiz content (sentences, words, questions, etc.)
- The quiz container will display all quiz materials separately
- Example: "Aquí tienes un ejercicio." or "Vamos a completar oraciones." or "Vamos a practicar pronunciación."
- Keep it conversational, not instructional
{language_note}"""
        else:
            # Help request, language question, or other
            instruction = f"""You are Hootie. Respond to the user's request:{profile_info}
{missing_info_prompt}
{language_question_prompt}

{language_note}

Correction JSON (use internally to adjust):
{input_dict.get('correction_json', '{}')}

Assessment JSON (use internally to adjust difficulty):
{input_dict.get('assessment_json', '{}')}

Plan JSON (use internally to guide content):
{input_dict.get('plan_json', '{}')}

Now reply briefly and naturally in {target_language if target_language else 'English'} (unless help exception applies)."""
    
    messages = [
        SystemMessage(content=system_prompt),
        *history,
        HumanMessage(content=input_dict["last_user"]),
        HumanMessage(content=instruction)
    ]
    
    # Use agentic LLM with tools
    response = await llm_with_tools.ainvoke(messages)
    
    # Handle tool calls if any (e.g., upsert_profile to save user info)
    if hasattr(response, 'tool_calls') and response.tool_calls:
        from langchain_core.messages import ToolMessage
        import uuid
        
        # Create a tool mapping for manual execution
        tool_map = {tool.name: tool for tool in tools}
        
        # Add the AIMessage with tool_calls to messages first (required for Gemini)
        messages.append(response)
        
        for tool_call in response.tool_calls:
            # Handle different tool_call formats (dict or object with attributes)
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                tool_call_id = tool_call.get("id") or tool_call.get("tool_call_id")
            else:
                # Tool call is an object with attributes - try common attribute names
                tool_name = getattr(tool_call, "name", None)
                tool_args = getattr(tool_call, "args", {})
                # Try multiple possible attribute names for tool_call_id
                tool_call_id = (
                    getattr(tool_call, "id", None) or 
                    getattr(tool_call, "tool_call_id", None) or
                    getattr(tool_call, "toolCallId", None) or
                    getattr(tool_call, "tool_call_id", None)
                )
            
            # Debug: print tool_call structure
            print(f"[Agent] 🔍 Tool call structure: name={tool_name}, id={tool_call_id}, type={type(tool_call)}")
            if not isinstance(tool_call, dict):
                print(f"[Agent] 🔍 Tool call attributes: {[attr for attr in dir(tool_call) if not attr.startswith('_')]}")
            
            # For Gemini, we need to use the exact tool_call_id from the response
            # If it's missing, we need to extract it from the response message
            if not tool_call_id or tool_call_id == "":
                # Try to get tool_call_id from the response message itself
                if hasattr(response, 'response_metadata') and response.response_metadata:
                    tool_call_id = response.response_metadata.get('tool_call_id')
                # If still missing, generate one
                if not tool_call_id:
                    tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
                    print(f"[Agent] ⚠️ Generated fallback tool_call_id: {tool_call_id}")
            
            if not tool_name:
                print(f"[Agent] ⚠️ Could not extract tool name from tool_call: {tool_call}")
                continue
            
            # Execute the tool manually
            if tool_name in tool_map:
                tool = tool_map[tool_name]
                try:
                    # Validate target_language if it's being set via upsert_profile
                    if tool_name == "upsert_profile":
                        patch = tool_args.get("patch", {})
                        if "target_language" in patch:
                            target_lang = patch["target_language"]
                            normalized_lang = normalize_language(target_lang)
                            if normalized_lang:
                                # Language is supported - normalize it
                                patch["target_language"] = normalized_lang
                                tool_args["patch"] = patch
                                print(f"[Agent] 🔧 LLM called upsert_profile tool with: {tool_args} (normalized language: {normalized_lang})")
                            else:
                                # Language is NOT supported - reject and inform LLM
                                supported_langs_str = ", ".join(SUPPORTED_LANGUAGES_LIST)
                                error_msg = f"ERROR: The language '{target_lang}' is not supported. Supported languages are: {supported_langs_str}. Please apologize to the user and ask them to choose one of the supported languages. Do NOT save this language to the profile."
                                print(f"[Agent] ⚠️ Unsupported language detected: {target_lang}")
                                tool_call_id_str = str(tool_call_id) if tool_call_id else f"call_{uuid.uuid4().hex[:8]}"
                                messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id_str, name=tool_name))
                                continue  # Skip executing the tool
                        else:
                            print(f"[Agent] 🔧 LLM called upsert_profile tool with: {tool_args}")
                    
                    tool_result = await tool.ainvoke(tool_args)
                    # Create ToolMessage with proper tool_call_id and name (required by Gemini)
                    # Ensure tool_call_id is a non-empty string
                    tool_call_id_str = str(tool_call_id) if tool_call_id else f"call_{uuid.uuid4().hex[:8]}"
                    tool_message = ToolMessage(content=str(tool_result), tool_call_id=tool_call_id_str, name=tool_name)
                    messages.append(tool_message)
                except Exception as e:
                    print(f"[Agent] ⚠️ Tool execution failed for {tool_name}: {e}")
                    import traceback
                    traceback.print_exc()
                    tool_call_id_str = str(tool_call_id) if tool_call_id else f"call_{uuid.uuid4().hex[:8]}"
                    messages.append(ToolMessage(content=f"Error: {str(e)}", tool_call_id=tool_call_id_str, name=tool_name))
            else:
                print(f"[Agent] ⚠️ Unknown tool: {tool_name}")
                tool_call_id_str = str(tool_call_id) if tool_call_id else f"call_{uuid.uuid4().hex[:8]}"
                messages.append(ToolMessage(content="Error: Unknown tool", tool_call_id=tool_call_id_str, name=tool_name or "unknown"))
        
        # If tools were called, invoke LLM again to get final response
        if response.tool_calls:
            response = await llm_with_tools.ainvoke(messages)
    
    return response.content

def build_agent():
    """Build the agentic tutor."""
    
    async def run_step(session_id: str, user: str) -> str:
        """Run a single step of the agent."""
        print(f"\n{'='*60}")
        print(f"[Agent] 🎯 Starting run_step")
        print(f"[Agent] Session: {session_id}")
        print(f"[Agent] User message: '{user[:100]}...' (length: {len(user)})")
        
        session = get_session(session_id)
        
        # Check if this is the first turn
        is_first_turn = len(session.get("history", [])) == 0
        print(f"[Agent] Is first turn: {is_first_turn}")
        
        # Check if user sent empty message (quiz completion trigger)
        is_quiz_completion = user.strip() == ""
        print(f"[Agent] Is quiz completion: {is_quiz_completion}")
        
        # For first turn, check if user already provided profile info
        if is_first_turn:
            # First, let the LLM process the message (it may extract and save profile info via tool calls)
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user,
                "is_first_turn": True,
                "correction_json": "{}",
                "assessment_json": "{}",
                "plan_json": "{}"
            })
            
            # Refresh profile after LLM response (it might have called upsert_profile tool)
            profile_str_after = await get_profile.ainvoke({"session_id": session_id})
            try:
                profile_after = json.loads(profile_str_after)
                target_language_set = bool(profile_after.get("target_language"))
                language_level_set = bool(profile_after.get("language_level"))
                can_start_quizzes = target_language_set and language_level_set
                
                if can_start_quizzes:
                    # User already provided target_language in first message - skip welcome, start quizzes
                    print(f"[Agent] ✅ Target language detected in first message: {profile_after.get('target_language')}")
                    print(f"[Agent] 🎯 Skipping welcome message, proceeding with quiz")
                    
                    # Update history with user message
                    session["history"].append({"role": "user", "content": user})
                    
                    # Select first quiz type
                    selected_test_type = TEST_TYPES[0]
                    
                    # Generate quiz intro message (LLM should have already acknowledged the info in 'reply')
                    quiz_reply = await tutor_reply({
                        "session_id": session_id,
                        "last_user": "",
                        "test_type": selected_test_type,
                        "last_quiz_result": None,
                        "quiz_based_assessment": None,
                        "missing_info": [],
                        "is_language_question": False,
                        "correction_json": "{}",
                        "assessment_json": "{}",
                        "plan_json": "{}"
                    })
                    
                    # Combine acknowledgment (if any) with quiz intro
                    if reply and not reply.strip().startswith("Hello") and not "tell me" in reply.lower():
                        # LLM gave a brief acknowledgment, combine with quiz
                        combined_reply = f"{reply}\n\n{quiz_reply}"
                    else:
                        # LLM gave welcome message, just use quiz reply (which should acknowledge)
                        combined_reply = quiz_reply
                    
                    session["history"].append({"role": "assistant", "content": combined_reply})
                    
                    # Return reply with quiz
                    return json.dumps({
                        "reply": combined_reply,
                        "test_type": selected_test_type,
                        "is_first_turn": False
                    }, ensure_ascii=False)
                else:
                    # No target_language yet - send welcome message
                    print(f"[Agent] ℹ️ No target language in first message, sending welcome")
            except Exception as e:
                print(f"[Agent] ⚠️ Error checking profile after first turn: {e}")
            
            # Update history
            session["history"].append({"role": "user", "content": user})
            session["history"].append({"role": "assistant", "content": reply})
            
            # Return reply (no test type for first turn)
            return json.dumps({
                "reply": reply,
                "test_type": None,
                "is_first_turn": True
            }, ensure_ascii=False)
        
        # Get current profile to check what's missing (initial check, will be refreshed after LLM processes message)
        profile_str = await get_profile.ainvoke({"session_id": session_id})
        try:
            current_profile = json.loads(profile_str)
        except:
            current_profile = {}
        
        # Profile extraction is handled by the LLM via the upsert_profile tool
        # We rely on the LLM to detect and save profile information from user messages
        # The LLM will call upsert_profile tool when it detects profile information
        # We check for profile updates after the LLM response (see below)
        
        # Initial check what profile information is still missing (will be re-checked after LLM processes message)
        missing_info = []
        if not current_profile.get("name"):
            missing_info.append("name")
        if not current_profile.get("age"):
            missing_info.append("age")
        if not current_profile.get("interests"):
            missing_info.append("interests")
        if not current_profile.get("target_language"):
            missing_info.append("target_language")
        if not current_profile.get("language_level"):
            missing_info.append("language_level")
        
        print(f"[Agent] 📋 Missing profile info (initial check): {missing_info}")
        
        # For subsequent turns: normal flow with test selection
        session = get_session(session_id)
        
        # Check if there are quiz results to assess
        quiz_results = session.get("quiz_results", [])
        last_quiz_result = None
        quiz_based_assessment = None
        
        # Assess overall proficiency from all quiz results (for adaptive difficulty)
        if quiz_results:
            quiz_results_summary = []
            total_score = 0
            for qr in quiz_results:
                quiz_results_summary.append(
                    f"Test: {qr['test_type']}, Score: {qr['score']*100:.1f}%, "
                    f"Input: {qr.get('user_input', 'N/A')[:100]}"
                )
                total_score += qr['score']
            
            avg_score = total_score / len(quiz_results) if quiz_results else 0
            quiz_summary_text = "\n".join(quiz_results_summary)
            quiz_summary_text += f"\n\nAverage Score: {avg_score*100:.1f}%\nTotal Tests: {len(quiz_results)}"
            
            # Get overall CEFR assessment from quiz results
            quiz_assess_result = await quiz_assess_chain.ainvoke({
                "quiz_results_summary": quiz_summary_text,
                "quiz_cefr_assessment": QUIZ_CEFR_ASSESSMENT
            })
            
            try:
                quiz_based_assessment = json.loads(quiz_assess_result)
            except:
                quiz_based_assessment = {"level": "A1", "reason": "Assessment pending", "average_score": avg_score}
        
        # If user sent empty message, they just completed a quiz - get last result for feedback
        if is_quiz_completion and quiz_results:
            last_quiz_result = quiz_results[-1]
        
        # Use LLM to understand user intent (help requests, language questions, test preferences, requested test type)
        is_help_request = False
        is_language_question = False
        requested_test_type = None
        test_type_preferences = {}
        
        if user and user.strip() and not is_quiz_completion:
            try:
                intent_result = await intent_detection_chain.ainvoke({"user_message": user})
                # Parse JSON from response
                intent_text = intent_result.strip()
                if intent_text.startswith("```json"):
                    intent_text = intent_text[7:]
                elif intent_text.startswith("```"):
                    intent_text = intent_text[3:]
                if intent_text.endswith("```"):
                    intent_text = intent_text[:-3].strip()
                
                intent_json = json.loads(intent_text)
                is_help_request = intent_json.get("is_help_request", False)
                is_language_question = intent_json.get("is_language_question", False)
                requested_test_type = intent_json.get("requested_test_type")
                test_type_preferences = intent_json.get("test_type_preferences", {})
                
                # Update test type preferences from LLM detection
                if test_type_preferences:
                    if "test_preferences" not in session:
                        session["test_preferences"] = {}
                    for test_type, weight in test_type_preferences.items():
                        if weight > 0:
                            session["test_preferences"][test_type] = session["test_preferences"].get(test_type, 0) + weight
                    print(f"[Agent] 🎯 Test type preferences updated from LLM: {session.get('test_preferences', {})}")
                
                print(f"[Agent] 🧠 LLM detected intent - is_help_request: {is_help_request}, is_language_question: {is_language_question}, requested_test_type: {requested_test_type}")
            except Exception as e:
                print(f"[Agent] ⚠️ Intent detection failed: {e}, defaulting to defaults")
                is_help_request = False
                is_language_question = False
                requested_test_type = None
                test_type_preferences = {}
        
        # CRITICAL: Do not start quizzes until target_language AND language_level are set
        target_language_set = bool(current_profile.get("target_language"))
        language_level_set = bool(current_profile.get("language_level"))
        can_start_quizzes = target_language_set and language_level_set
        selected_test_type = None
        
        if can_start_quizzes:
            
            # Quiz order logic: sequential until all types completed once, then consider preferences
            completed_types = set(result.get("test_type", "") for result in quiz_results)
            all_completed_once = all(t in completed_types for t in TEST_TYPES)
            
            # Get test preferences from session
            test_preferences = session.get("test_preferences", {})
            
            # If user explicitly requested a test type, use it immediately
            if requested_test_type and requested_test_type in TEST_TYPES:
                selected_test_type = requested_test_type
                print(f"[Agent] 🎯 User explicitly requested test type: {selected_test_type}")
            elif all_completed_once:
                # All quiz types completed at least once - use preferences or random
                if test_preferences:
                    # Weight test types by preferences
                    weighted_types = []
                    for test_type in TEST_TYPES:
                        weight = test_preferences.get(test_type, 1)
                        weighted_types.extend([test_type] * int(weight))
                    if weighted_types:
                        selected_test_type = random.choice(weighted_types)
                        print(f"[Agent] 🎯 Selected test type based on preferences: {selected_test_type} (preferences: {test_preferences})")
                    else:
                        selected_test_type = random.choice(TEST_TYPES)
                        print(f"[Agent] 🎲 Random test type (all completed once): {selected_test_type}")
                else:
                    selected_test_type = random.choice(TEST_TYPES)
                    print(f"[Agent] 🎲 Random test type (all completed once): {selected_test_type}")
            else:
                # Sequential order - find next uncompleted type
                for test_type in TEST_TYPES:
                    if test_type not in completed_types:
                        selected_test_type = test_type
                        break
                else:
                    # Fallback (should not happen)
                    selected_test_type = TEST_TYPES[0]
                print(f"[Agent] 📋 Sequential test type: {selected_test_type} (completed so far: {list(completed_types)})")
        else:
            print(f"[Agent] ⚠️ Cannot start quizzes - target_language: {target_language_set}, language_level: {language_level_set}")
        
        # 1. Assess CEFR level from conversation
        print(f"[Agent] 📊 Step 1: Assessing CEFR level...")
        assessment_result = await assess_chain.ainvoke({
            "last_user": user,
            "cefr_rubric": CEFR_RUBRIC
        })
        print(f"[Agent] 📊 Assessment result: {assessment_result[:200]}...")
        
        try:
            # Try to extract JSON from markdown code blocks
            assessment_text = assessment_result.strip()
            if assessment_text.startswith("```json"):
                assessment_text = assessment_text[7:]  # Remove ```json
            elif assessment_text.startswith("```"):
                assessment_text = assessment_text[3:]  # Remove ```
            if assessment_text.endswith("```"):
                assessment_text = assessment_text[:-3].strip()  # Remove closing ```
            
            assessment_json = json.loads(assessment_text)
            await save_assessment.ainvoke({
                "session_id": session_id,
                "assessment": assessment_json
            })
            print(f"[Agent] ✅ Assessment saved: {assessment_json.get('level', 'unknown')}")
        except Exception as e:
            assessment_json = {"level": "A1", "reason": "Parse error", "next_target": "Basic vocabulary"}
            print(f"[Agent] ⚠️ Assessment parse failed: {e}")
        
        # 2. Get correction
        print(f"[Agent] ✏️ Step 2: Getting correction...")
        correction_result = await correct_chain.ainvoke({
            "last_user": user,
            "correction_policy": CORRECTION_POLICY
        })
        print(f"[Agent] ✏️ Correction result: {correction_result[:200]}...")
        
        try:
            correction_json = json.loads(correction_result)
        except Exception as e:
            correction_json = correction_result
            print(f"[Agent] ⚠️ Correction parse failed: {e}")
        
        # 3. Plan lesson
        print(f"[Agent] 📚 Step 3: Planning lesson...")
        plan_result = await lesson_plan_func({
            "session_id": session_id,
            "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json)
        })
        print(f"[Agent] 📚 Lesson plan result: {plan_result[:200]}...")
        
        try:
            # Try to extract JSON from markdown code blocks
            plan_text = plan_result.strip()
            if plan_text.startswith("```json"):
                plan_text = plan_text[7:]  # Remove ```json
            elif plan_text.startswith("```"):
                plan_text = plan_text[3:]  # Remove ```
            if plan_text.endswith("```"):
                plan_text = plan_text[:-3].strip()  # Remove closing ```
            
            plan_json = json.loads(plan_text)
        except Exception as e:
            plan_json = {"objective": "Basic vocabulary", "prompt": "Practice basic words", "support": "Use simple examples", "difficulty": "A1"}
            print(f"[Agent] ⚠️ Lesson plan parse failed: {e}")
        
        # Intent detection already done above - reuse those results
        
        # 4. Generate tutor reply with test type, quiz feedback, and overall assessment
        # If this is a quiz completion (last_quiz_result exists), provide feedback
        # Otherwise, this is a new turn starting - generate brief intro with quiz
        print(f"[Agent] 💬 Step 4: Generating tutor reply...")
        print(f"[Agent] Context: last_quiz_result={last_quiz_result is not None}, is_help_request={is_help_request}, can_start_quizzes={can_start_quizzes}")
        
        # Generate the reply first (LLM might call upsert_profile tool during this)
        # We'll refresh the profile after to check if anything was saved
        
        if last_quiz_result:
            print(f"[Agent] 📝 Mode: Quiz feedback (last quiz: {last_quiz_result.get('test_type')}, score: {last_quiz_result.get('score', 0)*100:.1f}%)")
            # User just completed a quiz - provide VERY BRIEF feedback
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user,
                "test_type": None,  # No new quiz, just feedback
                "last_quiz_result": last_quiz_result,
                "quiz_based_assessment": quiz_based_assessment,
                "missing_info": missing_info,
                "is_language_question": is_language_question,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
            # Update history
            session["history"].append({"role": "user", "content": user})
            session["history"].append({"role": "assistant", "content": reply})
            
            # IMMEDIATELY start next turn with a new quiz (no waiting for user)
            # BUT only if we can start quizzes (target_language AND language_level set)
            if can_start_quizzes:
                # Quiz order logic for auto-progression after quiz completion
                last_quiz_type = last_quiz_result.get("test_type", "")
                completed_types = set(result.get("test_type", "") for result in quiz_results)
                all_completed_once = all(t in completed_types for t in TEST_TYPES)
                
                if all_completed_once:
                    # All quiz types completed at least once - use random order (avoid repeating last)
                    available_types = [t for t in TEST_TYPES if t != last_quiz_type]
                    if not available_types:
                        available_types = TEST_TYPES  # Fallback
                    selected_test_type = random.choice(available_types)
                    print(f"[Agent] 🎲 After feedback, random next quiz: {selected_test_type} (last was: {last_quiz_type})")
                else:
                    # Sequential order - find next uncompleted type
                    for test_type in TEST_TYPES:
                        if test_type not in completed_types:
                            selected_test_type = test_type
                            break
                    else:
                        # All types completed now, start random selection (avoid repeating last)
                        available_types = [t for t in TEST_TYPES if t != last_quiz_type]
                        if not available_types:
                            available_types = TEST_TYPES
                        selected_test_type = random.choice(available_types)
                    print(f"[Agent] 📋 After feedback, sequential next quiz: {selected_test_type} (last was: {last_quiz_type}, completed: {list(completed_types)})")
                
                # Generate a simple template-based intro message for the next quiz
                # Using templates instead of LLM to avoid unwanted conversational messages
                quiz_intros = {
                    "Spanish": {
                        "image_detection": "Aquí tienes un ejercicio de imágenes.",
                        "unit_completion": "Vamos a completar oraciones.",
                        "keyword_match": "Vamos a practicar vocabulario.",
                        "pronunciation": "Vamos a practicar pronunciación.",
                        "podcast": "Escucha esta conversación.",
                        "reading": "Lee este artículo."
                    },
                    "French": {
                        "image_detection": "Voici un exercice d'images.",
                        "unit_completion": "Complétons des phrases.",
                        "keyword_match": "Pratiquons le vocabulaire.",
                        "pronunciation": "Pratiquons la pronunciation.",
                        "podcast": "Écoute cette conversation.",
                        "reading": "Lis cet article."
                    },
                    "English": {
                        "image_detection": "Here's an image exercise.",
                        "unit_completion": "Let's complete some sentences.",
                        "keyword_match": "Let's practice vocabulary.",
                        "pronunciation": "Let's practice pronunciation.",
                        "podcast": "Listen to this conversation.",
                        "reading": "Read this article."
                    },
                    "Mandarin Chinese": {
                        "image_detection": "这是一个图像练习。",
                        "unit_completion": "我们来完成句子。",
                        "keyword_match": "我们来练习词汇。",
                        "pronunciation": "我们来练习发音。",
                        "podcast": "听这段对话。",
                        "reading": "读这篇文章。"
                    },
                    "Hindi": {
                        "image_detection": "यह एक चित्र अभ्यास है।",
                        "unit_completion": "आइए वाक्य पूरे करें।",
                        "keyword_match": "आइए शब्दावली का अभ्यास करें।",
                        "pronunciation": "आइए उच्चारण का अभ्यास करें।",
                        "podcast": "इस बातचीत को सुनें।",
                        "reading": "यह लेख पढ़ें।"
                    },
                    "Modern Standard Arabic": {
                        "image_detection": "إليك تمرين صور.",
                        "unit_completion": "لنكمل الجمل.",
                        "keyword_match": "لنتدرب على المفردات.",
                        "pronunciation": "لنتدرب على النطق.",
                        "podcast": "استمع إلى هذه المحادثة.",
                        "reading": "اقرأ هذا المقال."
                    },
                    "Bengali": {
                        "image_detection": "এখানে একটি ছবির অনুশীলন।",
                        "unit_completion": "আসুন বাক্য সম্পূর্ণ করি।",
                        "keyword_match": "আসুন শব্দভাণ্ডার অনুশীলন করি।",
                        "pronunciation": "আসুন উচ্চারণ অনুশীলন করি।",
                        "podcast": "এই কথোপকথন শুনুন।",
                        "reading": "এই নিবন্ধটি পড়ুন।"
                    },
                    "Portuguese": {
                        "image_detection": "Aqui está um exercício de imagens.",
                        "unit_completion": "Vamos completar frases.",
                        "keyword_match": "Vamos praticar vocabulário.",
                        "pronunciation": "Vamos praticar pronúncia.",
                        "podcast": "Ouça esta conversa.",
                        "reading": "Leia este artigo."
                    },
                    "Russian": {
                        "image_detection": "Вот упражнение с изображениями.",
                        "unit_completion": "Давайте дополним предложения.",
                        "keyword_match": "Давайте попрактикуем лексику.",
                        "pronunciation": "Давайте попрактикуем произношение.",
                        "podcast": "Послушайте этот разговор.",
                        "reading": "Прочитайте эту статью."
                    },
                    "Urdu": {
                        "image_detection": "یہ ایک تصویری مشق ہے۔",
                        "unit_completion": "آئیں جملے مکمل کریں۔",
                        "keyword_match": "آئیں الفاظ کی مشق کریں۔",
                        "pronunciation": "آئیں تلفظ کی مشق کریں۔",
                        "podcast": "یہ بات چیت سنیں۔",
                        "reading": "یہ مضمون پڑھیں۔"
                    },
                    # Default templates for unsupported languages (emojis as fallback)
                    "default": {
                        "image_detection": "🖼️",
                        "unit_completion": "✏️",
                        "keyword_match": "📝",
                        "pronunciation": "🗣️",
                        "podcast": "🎧",
                        "reading": "📖"
                    }
                }
                
                # Get the target language
                target_lang = current_profile.get("target_language", "English")
                
                # Get intro template (fallback to default if language not found)
                lang_intros = quiz_intros.get(target_lang, quiz_intros["default"])
                next_quiz_reply = lang_intros.get(selected_test_type, quiz_intros["default"][selected_test_type])
                
                print(f"[Agent] 📝 Generated template intro: '{next_quiz_reply}'")
                
                # Add to history
                session["history"].append({"role": "assistant", "content": reply})
                session["history"].append({"role": "assistant", "content": next_quiz_reply})
                
                # Return both messages combined, with test_type for the next quiz
                combined_reply = f"{reply}\n\n{next_quiz_reply}"
                result = json.dumps({
                    "reply": combined_reply,
                    "test_type": selected_test_type,
                    "quiz_feedback": True,
                    "auto_continue": True  # Signal that next quiz should start automatically
                }, ensure_ascii=False)
                print(f"[Agent] ✅ Returning quiz feedback + auto-started next quiz: {selected_test_type}")
                print(f"[Agent] Combined reply length: {len(combined_reply)} chars")
                print(f"{'='*60}\n")
                return result
            else:
                # Target language not set - just return feedback, no next quiz
                session["history"].append({"role": "user", "content": user})
                session["history"].append({"role": "assistant", "content": reply})
                
                result = json.dumps({
                    "reply": reply,
                    "test_type": None
                }, ensure_ascii=False)
                print(f"[Agent] ✅ Returning quiz feedback only (target language not set, no next quiz)")
                print(f"{'='*60}\n")
                return result
        elif is_help_request or is_language_question or (missing_info and not current_profile.get("target_language")):
            # Help request, language question, or missing critical info (target_language) - no quiz, just respond
            mode = "Help request" if is_help_request else ("Language question" if is_language_question else "Missing info")
            print(f"[Agent] 📝 Mode: {mode} (no quiz)")
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user,
                "test_type": None,
                "missing_info": missing_info,
                "is_language_question": is_language_question,
                "last_quiz_result": None,
                "quiz_based_assessment": quiz_based_assessment,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
            
            # ALWAYS refresh profile after LLM response (it might have called upsert_profile tool)
            profile_str_after = await get_profile.ainvoke({"session_id": session_id})
            try:
                current_profile_after = json.loads(profile_str_after)
                # Check if profile was updated (target_language or language_level)
                profile_updated = False
                target_lang_just_set = not current_profile.get("target_language") and current_profile_after.get("target_language")
                level_just_set = not current_profile.get("language_level") and current_profile_after.get("language_level")
                
                if target_lang_just_set or level_just_set:
                    print(f"[Agent] ✅ Profile updated via tool call - target_language: {current_profile_after.get('target_language')}, language_level: {current_profile_after.get('language_level')}")
                    current_profile = current_profile_after
                    target_language_set = bool(current_profile.get("target_language"))
                    language_level_set = bool(current_profile.get("language_level"))
                    can_start_quizzes = target_language_set and language_level_set
                    profile_updated = True
                    
                    # Re-check missing info
                    missing_info = []
                    if not current_profile.get("name"):
                        missing_info.append("name")
                    if not current_profile.get("age"):
                        missing_info.append("age")
                    if not current_profile.get("interests"):
                        missing_info.append("interests")
                    if not current_profile.get("target_language"):
                        missing_info.append("target_language")
                    if not current_profile.get("language_level"):
                        missing_info.append("language_level")
                    print(f"[Agent] 📋 Missing info after tool call: {missing_info}")
                    
                    # If we can now start quizzes, generate quiz response immediately
                    if can_start_quizzes and not selected_test_type:
                        print(f"[Agent] 🎯 Can now start quizzes (target_language + language_level set) - generating quiz immediately")
                        selected_test_type = TEST_TYPES[0]
                        quiz_reply = await tutor_reply({
                            "session_id": session_id,
                            "last_user": "",
                            "test_type": selected_test_type,
                            "last_quiz_result": None,
                            "quiz_based_assessment": quiz_based_assessment,
                            "missing_info": missing_info,
                            "is_language_question": False,
                            "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                            "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                            "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
                        })
                        
                        # Use LLM's original reply if it's a brief acknowledgment, otherwise use quiz reply
                        # Rely on LLM understanding - if reply is asking for more info, replace with quiz
                        # If it's acknowledging, combine with quiz
                        if reply and len(reply) < 150:
                            combined_reply = f"{reply}\n\n{quiz_reply}"
                        else:
                            # LLM gave a longer message (probably asking for info) - replace with quiz intro
                            combined_reply = quiz_reply
                        
                        session["history"].append({"role": "user", "content": user})
                        session["history"].append({"role": "assistant", "content": combined_reply})
                        
                        result = json.dumps({
                            "reply": combined_reply,
                            "test_type": selected_test_type
                        }, ensure_ascii=False)
                        print(f"[Agent] ✅ Returning response with quiz (can_start_quizzes now True)")
                        print(f"[Agent] Reply length: {len(combined_reply)} chars")
                        print(f"{'='*60}\n")
                        return result
            except Exception as e:
                print(f"[Agent] ⚠️ Error refreshing profile after tool call: {e}")
                import traceback
                traceback.print_exc()
            
            session["history"].append({"role": "user", "content": user})
            session["history"].append({"role": "assistant", "content": reply})
            
            result = json.dumps({
                "reply": reply,
                "test_type": None
            }, ensure_ascii=False)
            print(f"[Agent] ✅ Returning help response (no quiz)")
            print(f"[Agent] Reply length: {len(reply)} chars")
            print(f"{'='*60}\n")
            return result
        else:
            # New turn starting (regular user message or turn start)
            # Only include a quiz if we can start quizzes and it's not a help request
            # Use LLM to determine if user wants to chat - if is_help_request is False and user sent a message, they might want to chat
            # But if can_start_quizzes is True, prioritize quizzes unless LLM detected explicit chat intent
            if can_start_quizzes and selected_test_type and not is_help_request:
                print(f"[Agent] 📝 Mode: New turn starting with quiz: {selected_test_type}")
            else:
                print(f"[Agent] 📝 Mode: New turn starting (no quiz - can_start_quizzes: {can_start_quizzes}, selected_test_type: {selected_test_type}, is_help_request: {is_help_request})")
            
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user if user else "Ready for next lesson",
                "test_type": selected_test_type if (can_start_quizzes and not is_help_request) else None,
                "last_quiz_result": None,
                "quiz_based_assessment": quiz_based_assessment,
                "missing_info": missing_info,
                "is_language_question": is_language_question,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
            print(f"[Agent] 💬 Tutor reply generated: {reply[:150]}...")
            
            # ALWAYS refresh profile after LLM response (it might have called upsert_profile tool)
            profile_str_after = await get_profile.ainvoke({"session_id": session_id})
            try:
                current_profile_after = json.loads(profile_str_after)
                # Check if profile was updated (target_language or language_level)
                profile_updated = False
                target_lang_just_set = not current_profile.get("target_language") and current_profile_after.get("target_language")
                level_just_set = not current_profile.get("language_level") and current_profile_after.get("language_level")
                
                if target_lang_just_set or level_just_set:
                    print(f"[Agent] ✅ Profile updated via tool call - target_language: {current_profile_after.get('target_language')}, language_level: {current_profile_after.get('language_level')}")
                    current_profile = current_profile_after
                    target_language_set = bool(current_profile.get("target_language"))
                    language_level_set = bool(current_profile.get("language_level"))
                    can_start_quizzes = target_language_set and language_level_set
                    profile_updated = True
                    
                    # Re-check missing info
                    missing_info = []
                    if not current_profile.get("name"):
                        missing_info.append("name")
                    if not current_profile.get("age"):
                        missing_info.append("age")
                    if not current_profile.get("interests"):
                        missing_info.append("interests")
                    if not current_profile.get("target_language"):
                        missing_info.append("target_language")
                    if not current_profile.get("language_level"):
                        missing_info.append("language_level")
                    print(f"[Agent] 📋 Missing info after tool call: {missing_info}")
                    
                    # If we can now start quizzes, generate quiz response immediately
                    if can_start_quizzes and not selected_test_type:
                        print(f"[Agent] 🎯 Can now start quizzes (target_language + language_level set) - generating quiz immediately")
                        selected_test_type = TEST_TYPES[0]
                        quiz_reply = await tutor_reply({
                            "session_id": session_id,
                            "last_user": "",
                            "test_type": selected_test_type,
                            "last_quiz_result": None,
                            "quiz_based_assessment": quiz_based_assessment,
                            "missing_info": missing_info,
                            "is_language_question": False,
                            "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                            "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                            "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
                        })
                        
                        # Use LLM's original reply if it's a brief acknowledgment, otherwise use quiz reply
                        # Rely on LLM understanding - if reply is asking for more info, replace with quiz
                        # If it's acknowledging, combine with quiz
                        if reply and len(reply) < 150 and not any(phrase in reply.lower() for phrase in ["tell me", "could you", "what", "which", "please share", "I'd like"]):
                            reply = f"{reply}\n\n{quiz_reply}"
                        else:
                            reply = quiz_reply
                        print(f"[Agent] 💬 Updated tutor reply with quiz: {reply[:150]}...")
            except Exception as e:
                print(f"[Agent] ⚠️ Error refreshing profile after tool call: {e}")
            
            # Save to history for regular messages
            if user and user.strip() and not is_quiz_completion:
                session["history"].append({"role": "user", "content": user})
                session["history"].append({"role": "assistant", "content": reply})
                print(f"[Agent] 💾 Saved to history")
            
            result = json.dumps({
                "reply": reply,
                "test_type": selected_test_type if (can_start_quizzes and not is_help_request) else None
            }, ensure_ascii=False)
            print(f"[Agent] ✅ Returning reply + quiz type: {selected_test_type if can_start_quizzes else None}")
            print(f"[Agent] Reply length: {len(reply)} chars")
            print(f"{'='*60}\n")
            return result
    
    return run_step

