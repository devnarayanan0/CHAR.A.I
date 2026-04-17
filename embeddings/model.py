from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-base-en-v1.5")

def embed(text: str):
    return model.encode(
        "Represent this sentence for searching relevant passages: " + text,
        normalize_embeddings=True
    )