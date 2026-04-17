from pinecone import Pinecone
import os

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("your-index-name")  # replace with your index

def query_pinecone(vector, top_k=3):
    res = index.query(
        vector=vector.tolist(),
        top_k=top_k,
        include_metadata=True
    )

    chunks = []
    for match in res["matches"]:
        chunks.append(match["metadata"]["text"])

    return chunks