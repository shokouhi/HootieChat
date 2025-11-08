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
    "unit_completion",      # (1) Unit completion tasks
    "keyword_match",        # (2) Rapid review keyword match
    "pronunciation",        # (3) Pronunciation
    "podcast",              # (4) Podcast listening
    "reading",              # (5) Reading comprehension
    "image_detection"       # (6) Image detection/recognition
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
    ("human", "Evaluate this user's overall Spanish proficiency based on ALL their quiz results:\n\n{quiz_results_summary}\n\nRubric:\n{quiz_cefr_assessment}")
])

quiz_assess_chain = quiz_assess_prompt | llm | StrOutputParser()

# Quiz performance scorer → JSON (0-100 score)
quiz_scorer_prompt = ChatPromptTemplate.from_messages([
    ("system", QUIZ_PERFORMANCE_SCORER),
    ("human", "Quiz Type: {test_type}\nStudent's Response: {user_input}\nExpected Answer/Criteria: {expected_info}\nRaw Metrics (if applicable): {raw_metrics}\nDifficulty Level: {difficulty_level}")
])

quiz_scorer_chain = quiz_scorer_prompt | llm | StrOutputParser()

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
async def tutor_reply(input_dict: Dict[str, Any]) -> str:
    """Generate tutor reply using agentic function calling."""
    session = get_session(input_dict["session_id"])
    history = [
        HumanMessage(content=m["content"]) if m["role"] == "user" 
        else AIMessage(content=m["content"])
        for m in session.get("history", [])
    ]
    
    # Check if this is the first turn (passed from run_step)
    is_first_turn = input_dict.get("is_first_turn", False)
    
    # Check if user is asking for help in English
    user_msg_lower = input_dict["last_user"].lower()
    help_keywords = ["help", "don't understand", "don't follow", "can't understand", "confused", "what does", "explain"]
    needs_help = any(keyword in user_msg_lower for keyword in help_keywords) and any(word in user_msg_lower for word in ["english", "eng", "help me"])
    
    # Get selected test type for this turn (skip for first turn)
    selected_test_type = input_dict.get("test_type", None)
    
    # Use appropriate prompt
    if is_first_turn:
        # First turn: English prompt to collect info
        from prompts import FIRST_TURN_PROMPT
        system_prompt = FIRST_TURN_PROMPT
        instruction = """Welcome the user and explain how the app works. Ask them to share:
- Their name
- Their age (or age range)
- Their interests/hobbies
- Their current Spanish level

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
            
            Internal assessment (use to adjust your Spanish complexity, but DON'T mention levels/scores to user):
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
            target_language = profile.get("target_language", "Spanish")  # Default to Spanish for backward compatibility
            stated_level = profile.get("language_level") or profile.get("spanish_level")  # Support both for backward compatibility
            if target_language:
                profile_parts.append(f"Target Language: {target_language}")
            if stated_level:
                profile_parts.append(f"Stated Language Level: {stated_level} (use this as base for content difficulty)")
            if profile_parts:
                profile_info = f"\n\nUser Profile:\n{', '.join(profile_parts)}"
        
        language_note = ""
        if needs_help:
            target_lang = profile.get("target_language", "Spanish") if profile else "Spanish"
            language_note = f"\n\nNOTE: User asked for help in English. You may respond briefly in English to clarify, then continue in {target_lang}."
        
        # Determine instruction based on context
        # Get target language from profile
        target_language = profile.get("target_language", "Spanish") if profile else "Spanish"
        
        if last_quiz_result:
            # User just completed a quiz - provide brief feedback ONLY (no transition - that happens separately)
            instruction = f"""You are Hootie. The student just completed a quiz. Provide VERY BRIEF feedback (1 sentence max) in {target_language}:{profile_info}

{quiz_feedback_section}
{assessment_section}

IMPORTANT: This is ONLY the feedback message. Do NOT transition to the next quiz or say anything about what's coming next. Just give the feedback and stop."""
        elif selected_test_type:
            # New turn starting with a quiz
            instruction = f"""You are Hootie. A new lesson turn is starting. NO GREETINGS - just briefly introduce the quiz naturally in {target_language}:{profile_info}

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
            # Help request or other
            instruction = f"""You are Hootie. Respond to the user's request:{profile_info}

{language_note}

Correction JSON (use internally to adjust):
{input_dict.get('correction_json', '{}')}

Assessment JSON (use internally to adjust difficulty):
{input_dict.get('assessment_json', '{}')}

Plan JSON (use internally to guide content):
{input_dict.get('plan_json', '{}')}

Now reply briefly and naturally in {target_language} (unless help exception applies)."""
    
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
        from langchain_core.tools import ToolExecutor
        from langchain_core.messages import ToolMessage
        
        tool_executor = ToolExecutor({tool.name: tool for tool in tools})
        
        for tool_call in response.tool_calls:
            tool_result = await tool_executor.ainvoke(tool_call)
            # Add tool result to messages for LLM to continue
            messages.append(ToolMessage(content=str(tool_result), tool_call_id=tool_call.get("id", "")))
        
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
        
        # For first turn, skip assessment/correction/planning and go straight to welcome
        if is_first_turn:
            # Generate welcome message in English
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user,
                "is_first_turn": True,
                "correction_json": "{}",
                "assessment_json": "{}",
                "plan_json": "{}"
            })
            
            # Update history
            session["history"].append({"role": "user", "content": user})
            session["history"].append({"role": "assistant", "content": reply})
            
            # Return reply (no test type for first turn)
            return json.dumps({
                "reply": reply,
                "test_type": None,
                "is_first_turn": True
            }, ensure_ascii=False)
        
        # After first turn: Check if user provided their info and extract/save it
        # If this is turn 2 (one user message + one assistant message in history), extract profile info
        if len(session.get("history", [])) == 2:
            # User just responded with their info - extract and save it
            user_response = user.lower()
            profile_updates = {}
            
            # Extract name (look for "name is", "I'm", "call me", etc.)
            import re
            name_patterns = [
                r"(?:name is|i'?m|call me|my name'?s?)\s+([A-Z][a-z]+)",
                r"(?:name:)\s*([A-Z][a-z]+)"
            ]
            for pattern in name_patterns:
                match = re.search(pattern, user, re.IGNORECASE)
                if match:
                    profile_updates["name"] = match.group(1)
                    break
            
            # Extract age
            age_patterns = [
                r"(?:age|i'?m|years? old)\s*(?:is|am|are)?\s*(\d+)",
                r"(\d+)\s*(?:years? old|age)"
            ]
            for pattern in age_patterns:
                match = re.search(pattern, user, re.IGNORECASE)
                if match:
                    profile_updates["age"] = match.group(1)
                    break
            
            # Extract interests - improved extraction
            interests_section = ""
            # Try multiple patterns to catch interests
            # Pattern 1: "I like X", "I enjoy X", "I love X", "my hobby is X"
            like_patterns = [
                r"(?:i\s+)?(?:like|enjoy|love|play|do)\s+(?:playing\s+)?([a-z]+(?:\s+[a-z]+)*?)(?:\s|$|,|\.)",
                r"(?:my\s+)?(?:hobby|interest|interests|favorite)\s+(?:is|are|include)\s+([a-z]+(?:\s+[a-z]+)*?)(?:\s|$|,|\.)",
                r"(?:interested\s+in|into)\s+([a-z]+(?:\s+[a-z]+)*?)(?:\s|$|,|\.)"
            ]
            for pattern in like_patterns:
                match = re.search(pattern, user_response, re.IGNORECASE)
                if match:
                    interests_section = match.group(1).strip()
                    # Clean up common words but keep the main interest
                    interests_section = re.sub(r'^\s*(?:the|a|an|my|playing|to)\s+', '', interests_section, flags=re.IGNORECASE)
                    if interests_section and len(interests_section) > 2:
                        # Remove trailing punctuation and limit length
                        interests_section = re.sub(r'[^\w\s]+$', '', interests_section)
                        profile_updates["interests"] = interests_section[:200]
                        print(f"[Agent] 📝 Extracted interests: '{interests_section}'")
                        break
            
            # Pattern 2: Look for common interest words in the text (tennis, music, etc.)
            if "interests" not in profile_updates:
                common_interests = ["tennis", "football", "soccer", "basketball", "music", "guitar", "piano", "reading", "books", 
                                  "cooking", "travel", "traveling", "photography", "art", "drawing", "gaming", "video games",
                                  "cycling", "running", "yoga", "dancing", "singing", "movies", "cinema", "theater"]
                for interest in common_interests:
                    if interest in user_response:
                        profile_updates["interests"] = interest
                        print(f"[Agent] 📝 Detected interest keyword: '{interest}'")
                        break
            
            # Extract target language
            language_patterns = [
                r"(?:want to learn|learning|learn|language is|studying)\s+(spanish|french|german|italian|portuguese|chinese|japanese|korean|russian|arabic|dutch|polish|swedish|norwegian|danish|finnish|turkish|greek|hebrew|hindi|thai|vietnamese)",
                r"(spanish|french|german|italian|portuguese|chinese|japanese|korean|russian|arabic|dutch|polish|swedish|norwegian|danish|finnish|turkish|greek|hebrew|hindi|thai|vietnamese)\s+(?:language|is what i want|is what i'm learning)"
            ]
            for pattern in language_patterns:
                match = re.search(pattern, user_response, re.IGNORECASE)
                if match:
                    lang_str = match.group(1).capitalize()
                    profile_updates["target_language"] = lang_str
                    print(f"[Agent] 📝 Extracted target language: '{lang_str}'")
                    break
            
            # Extract language level (for the target language)
            from quiz_generators.utils import normalize_cefr_level
            level_patterns = [
                r"(?:level|language level|i'?m)\s*(?:is|am|are)?\s*(beginner|intermediate|advanced|a1|a2|b1|b2|c1|c2|basic|basico|intermedio|avanzado)",
                r"(beginner|intermediate|advanced|a1|a2|b1|b2|c1|c2|basic|basico|intermedio|avanzado)\s*(?:level)?",
                r"i'?m\s+(?:a|an)?\s*(beginner|intermediate|advanced)"
            ]
            for pattern in level_patterns:
                match = re.search(pattern, user_response, re.IGNORECASE)
                if match:
                    level_str = match.group(1)
                    normalized_level = normalize_cefr_level(level_str)
                    profile_updates["language_level"] = normalized_level
                    print(f"[Agent] 📝 Extracted language level: {level_str} → {normalized_level}")
                    break
            
            # Save profile updates if any found
            if profile_updates:
                print(f"[Agent] 💾 Saving profile updates: {profile_updates}")
                await upsert_profile.ainvoke({
                    "session_id": session_id,
                    "patch": profile_updates
                })
        
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
        
        # Quiz order logic: sequential until all types completed once, then random
        completed_types = set(result.get("test_type", "") for result in quiz_results)
        all_completed_once = all(t in completed_types for t in TEST_TYPES)
        
        if all_completed_once:
            # All quiz types completed at least once - use random order
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
        
        # Check if user is asking for help (no quiz for help requests)
        user_msg_lower = user.lower()
        help_keywords = ["help", "don't understand", "don't follow", "can't understand", "confused", "what does", "explain"]
        is_help_request = any(keyword in user_msg_lower for keyword in help_keywords)
        print(f"[Agent] Help request detected: {is_help_request}")
        
        # 4. Generate tutor reply with test type, quiz feedback, and overall assessment
        # If this is a quiz completion (last_quiz_result exists), provide feedback
        # Otherwise, this is a new turn starting - generate brief intro with quiz
        print(f"[Agent] 💬 Step 4: Generating tutor reply...")
        print(f"[Agent] Context: last_quiz_result={last_quiz_result is not None}, is_help_request={is_help_request}")
        
        if last_quiz_result:
            print(f"[Agent] 📝 Mode: Quiz feedback (last quiz: {last_quiz_result.get('test_type')}, score: {last_quiz_result.get('score', 0)*100:.1f}%)")
            # User just completed a quiz - provide VERY BRIEF feedback
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user,
                "test_type": None,  # No new quiz, just feedback
                "last_quiz_result": last_quiz_result,
                "quiz_based_assessment": quiz_based_assessment,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
            # Update history
            session["history"].append({"role": "user", "content": user})
            session["history"].append({"role": "assistant", "content": reply})
            
            # IMMEDIATELY start next turn with a new quiz (no waiting for user)
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
            
            # Generate intro message for the next quiz
            next_quiz_reply = await tutor_reply({
                "session_id": session_id,
                "last_user": "",  # Empty - we're auto-starting
                "test_type": selected_test_type,
                "last_quiz_result": None,
                "quiz_based_assessment": quiz_based_assessment,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
            
            # Combine feedback and next quiz intro - both sent together
            # But feedback should be separate from quiz intro
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
        elif is_help_request:
            # Help request - no quiz, just respond
            print(f"[Agent] 📝 Mode: Help request (no quiz)")
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user,
                "test_type": None,
                "last_quiz_result": None,
                "quiz_based_assessment": quiz_based_assessment,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
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
            # Always include a quiz unless it's a help request
            print(f"[Agent] 📝 Mode: New turn starting with quiz: {selected_test_type}")
            reply = await tutor_reply({
                "session_id": session_id,
                "last_user": user if user else "Ready for next lesson",
                "test_type": selected_test_type if not is_help_request else None,
                "last_quiz_result": None,
                "quiz_based_assessment": quiz_based_assessment,
                "correction_json": correction_json if isinstance(correction_json, str) else json.dumps(correction_json),
                "assessment_json": assessment_json if isinstance(assessment_json, str) else json.dumps(assessment_json),
                "plan_json": plan_json if isinstance(plan_json, str) else json.dumps(plan_json)
            })
            print(f"[Agent] 💬 Tutor reply generated: {reply[:150]}...")
            
            # Save to history for regular messages
            if user and user.strip() and not is_quiz_completion:
                session["history"].append({"role": "user", "content": user})
                session["history"].append({"role": "assistant", "content": reply})
                print(f"[Agent] 💾 Saved to history")
            
            result = json.dumps({
                "reply": reply,
                "test_type": selected_test_type if not is_help_request else None
            }, ensure_ascii=False)
            print(f"[Agent] ✅ Returning reply + quiz type: {selected_test_type}")
            print(f"[Agent] Reply length: {len(reply)} chars")
            print(f"{'='*60}\n")
            return result
    
    return run_step

