from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    PROVIDER = os.getenv("PROVIDER", "openai")  # 'openai' | 'google'
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "")  # For Vertex AI
    GOOGLE_LOCATION = os.getenv("GOOGLE_LOCATION", "us-central1")  # Vertex AI location
    
    # Model selection
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")  # gpt-4, gpt-3.5-turbo, gpt-4-turbo
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash-lite")  # gemini-2.5-flash-lite (fastest), gemini-1.5-flash-latest, gemini-pro
    
    PORT = int(os.getenv("PORT", "3002"))  # Changed to 3002 to avoid conflict
    
    @classmethod
    def validate(cls):
        if cls.PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            print("⚠️ OPENAI_API_KEY is missing.")
        if cls.PROVIDER == "google" and not cls.GOOGLE_API_KEY:
            print("⚠️ GOOGLE_API_KEY is missing.")

CONFIG = Config()
CONFIG.validate()

