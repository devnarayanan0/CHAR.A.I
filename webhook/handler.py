from fastapi import Request
from fastapi.responses import PlainTextResponse, JSONResponse
import os
from dotenv import load_dotenv
from rag.pipeline import run_rag

# 🔹 Load env
load_dotenv()
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")


# 🔹 GET → Meta verification
async def verify(req: Request):
    params = req.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_TOKEN:
        return PlainTextResponse(content=challenge)

    return JSONResponse(content={"error": "verification failed"}, status_code=403)


# 🔹 POST → Incoming messages
async def webhook(req: Request):
    data = await req.json()

    try:
        entry = data.get("entry", [])
        for e in entry:
            changes = e.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    from_number = msg.get("from")
                    text = msg.get("text", {}).get("body")

                    print(f"User: {from_number}")
                    print(f"Message: {text}")

                    if text:
                        answer = run_rag(text)
                        print(f"Answer: {answer}")

    except Exception as e:
        print("Error parsing message:", str(e))

    return JSONResponse(content={"status": "received"}, status_code=200)