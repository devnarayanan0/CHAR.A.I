import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_name = "WhatsApp RAG Chatbot"

    whatsapp_verify_token = os.getenv("VERIFY_TOKEN", os.getenv("WHATSAPP_TOKEN", ""))
    whatsapp_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_test_number = os.getenv("WHATSAPP_TEST_NUMBER", "")
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    groq_model_name = os.getenv("GROQ_MODEL_NAME", "llama-3.1-8b-instant")
    rag_service_url = os.getenv("RAG_SERVICE_URL", "").rstrip("/")

    pinecone_api_key = os.getenv("PINECONE_API_KEY", "")
    pinecone_index_name = os.getenv("PINECONE_INDEX_NAME", "base-char-ai").strip()
    pinecone_dimension = int(os.getenv("PINECONE_DIMENSION", "768"))

    embedding_model_name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-base-en-v1.5")
    data_dir = os.getenv("DATA_DIR", "data")

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_KEY", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
