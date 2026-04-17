from embeddings.model import embed
from vectordb.pinecone_client import query_pinecone
import requests
import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def ask_llm(query, context):
    prompt = f"""
Answer using context below:

{context}

Question: {query}
"""

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
    )

    return response.json()["choices"][0]["message"]["content"]


def run_rag(query: str):
    vector = embed(query)
    chunks = query_pinecone(vector)

    context = "\n".join(chunks)

    answer = ask_llm(query, context)

    return answer