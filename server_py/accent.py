import azure.cognitiveservices.speech as speechsdk
import os
from dotenv import load_dotenv

load_dotenv()

azure_key = os.getenv("AZURE_SPEECH_KEY")
azure_region = os.getenv("AZURE_SPEECH_REGION", "eastus")

if not azure_key:
    raise ValueError("AZURE_SPEECH_KEY environment variable is required")

speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
# Use WAV file from parent directory
audio_config = speechsdk.audio.AudioConfig(filename="../user_spanish3.wav")

pron_cfg = speechsdk.PronunciationAssessmentConfig(
    reference_text="Hola, me gusta el tenis.",
    grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
    granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
    enable_miscue=True
)

rec = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config, language="es-ES")
pron_cfg.apply_to(rec)
result = rec.recognize_once()

assessment = speechsdk.PronunciationAssessmentResult(result)
print(assessment.accuracy_score, assessment.fluency_score, assessment.completeness_score)
# Also inspect assessment.json_result for per-word/phoneme detail