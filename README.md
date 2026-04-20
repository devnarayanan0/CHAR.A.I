# CHAR.A.I User Guide

## 1. System Flow Overview

This system works in this order:

`data/` -> local ingestion -> BGE embedding (768) -> Pinecone (`base-char-ai`) -> retrieval -> Groq LLM -> response

### What happens when the server starts
1. FastAPI starts.
2. The app automatically scans the local `data/` folder.
3. It reads supported files: `.txt`, `.md`, `.pdf`.
4. It splits file text into chunks of 500 characters with 50-character overlap.
5. Each chunk is embedded using the BGE embedding model.
6. Embeddings are uploaded to the Pinecone index `base-char-ai`.
7. A local ingestion state file prevents duplicate uploads for unchanged files.

### What happens when a request is sent
1. A request hits `POST /webhook`.
2. The app reads the user name and message.
3. The message is embedded using the same BGE model.
4. Pinecone is queried for the most relevant chunks.
5. Retrieved chunks are joined into context.
6. The context and user question are sent to Groq.
7. The model returns an answer.
8. A minimal in-memory log is stored with:
   - `user`
   - `timestamp`

## 2. How To Run Locally

### Step 1: Install dependencies
```bash
pip install -r requirements.txt
```

What this does:
- Installs FastAPI
- Installs the BGE embedding stack
- Installs Pinecone client
- Installs PDF support
- Installs the HTTP client used for Groq

### Step 2: Start the server
```bash
uvicorn app.main:app --reload
```

What this does:
- Starts the FastAPI server locally
- Enables auto-reload when files change

What you should see:
- Uvicorn startup logs
- A message that local document ingestion started
- A message showing ingestion results
- Server listening on `http://127.0.0.1:8000`

Typical startup output looks like:
```text
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:app.main:Starting local document ingestion
INFO:app.main:Local document ingestion complete: {...}
```

### Step 3: Start local RAG with Cloudflare Tunnel
```bash
./start.sh
```

This command:
- starts the local RAG service on port `8001`
- starts Cloudflare Tunnel using `cloudflared tunnel run rag-tunnel`
- prints the public URL to use from Railway

Set this in Railway:
```text
RAG_SERVICE_URL=https://rag.yourdomain.com
```

## 3. What Opens Where

### Base API
```text
http://127.0.0.1:8000
```

### Swagger UI
```text
http://127.0.0.1:8000/docs
```

### What Swagger UI is
Swagger UI is the built-in FastAPI API dashboard.

It lets you:
- See all available endpoints
- Open an endpoint
- Fill request bodies directly in the browser
- Run requests without Postman or curl
- Inspect responses live

## 4. Admin Dashboard Usage

Open:
```text
http://127.0.0.1:8000/docs
```

You will see the available routes.

### `POST /admin/ingest`
Use this to manually rescan `data/` and upload new or changed files.

#### Steps in Swagger UI
1. Open `/admin/ingest`
2. Click `Try it out`
3. Click `Execute`

#### Expected response
```json
{
  "status": "ok",
  "result": {
    "processed_files": 1,
    "removed_files": 0,
    "skipped_files": 0,
    "uploaded_chunks": 12
  }
}
```

What the fields mean:
- `processed_files`: number of changed/new files ingested
- `removed_files`: files removed from Pinecone because they no longer exist locally
- `skipped_files`: unreadable or empty files skipped
- `uploaded_chunks`: total chunks uploaded to Pinecone

### `GET /admin/logs`
Use this to see recent minimal logs.

#### Steps in Swagger UI
1. Open `/admin/logs`
2. Click `Try it out`
3. Optionally set `limit`
4. Click `Execute`

#### Expected response
```json
{
  "logs": [
    {
      "user": "dev",
      "timestamp": "2026-04-17T10:31:10.269345+00:00"
    }
  ]
}
```

## 5. How To Add Data

Put your source files inside the local `data/` folder.

### Supported formats
- `.txt`
- `.md`
- `.pdf`

### Example
```text
data/
  company_overview.txt
  faq.md
  manual.pdf
```

### After adding files
Choose one of these:

#### Option 1: Restart the server
When the server starts, it automatically ingests `data/`.

#### Option 2: Run manual ingestion
Use:
- Swagger UI: `POST /admin/ingest`
- or `curl`

```bash
curl -X POST http://127.0.0.1:8000/admin/ingest
```

## 6. How Ingestion Works

When ingestion runs:
1. The system scans `data/`
2. It reads all supported files
3. It extracts text
4. It splits text into chunks of 500 characters with 50 overlap
5. It generates BGE embeddings for each chunk
6. It uploads vectors to Pinecone index `base-char-ai`
7. It stores local file hashes so unchanged files are not uploaded again

### What success looks like
- `POST /admin/ingest` returns `status: ok`
- `uploaded_chunks` is greater than `0`
- Pinecone contains vectors
- Asking questions starts returning context-aware answers

## 7. How To Test The System

Use `POST /webhook`.

### Example request body
```json
{
  "user": "dev",
  "message": "What is CHAR.A.I?"
}
```

### In Swagger UI
1. Open `/webhook`
2. Click `Try it out`
3. Paste the example body
4. Click `Execute`

### Example response
```json
{
  "user": "dev",
  "answer": "...",
  "context": [
    "retrieved chunk 1",
    "retrieved chunk 2"
  ]
}
```

### What happens internally
1. The message is embedded with BGE
2. Pinecone retrieves relevant chunks
3. The chunks are sent as context to Groq
4. Groq generates the answer
5. The request is logged in memory with user and timestamp only

## 8. How To Verify RAG Is Working

### Before ingestion
You may see:
- generic answers
- fallback answers like `I do not know`
- empty `context: []`

This means Pinecone has no useful vectors yet.

### After ingestion
You should see:
- non-empty `context`
- answers grounded in your local documents
- better responses for questions related to the files in `data/`

### Simple verification method
1. Add a file with a unique sentence to `data/`
2. Run `POST /admin/ingest`
3. Ask a question about that sentence using `POST /webhook`
4. Confirm the answer uses the ingested content

## 9. Common Issues & Fixes

### Problem: Server not starting
Possible causes:
- dependencies not installed
- wrong Python environment
- missing environment variables

Fix:
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Check that these environment variables exist:
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `GROQ_API_KEY`
- `WHATSAPP_TOKEN`

### Problem: Empty responses or generic answers
Possible causes:
- no files in `data/`
- ingestion not run
- Pinecone index has no vectors

Fix:
1. Add files to `data/`
2. Restart server or run `POST /admin/ingest`
3. Test again

### Problem: No Pinecone results
Possible causes:
- wrong Pinecone index name
- empty index
- ingestion did not upload chunks

Fix:
- verify `PINECONE_INDEX_NAME=base-char-ai`
- run ingestion again
- check the ingestion response for `uploaded_chunks`

### Problem: No data in `data/`
Fix:
- add `.txt`, `.md`, or `.pdf` files
- restart server or call `/admin/ingest`

### Problem: `POST /webhook` returns 400
Cause:
- payload shape is invalid

Use this format:
```json
{
  "user": "dev",
  "message": "your question"
}
```

## 10. How To Deploy Globally (Render)

### Step 1: Push the project to GitHub
```bash
git add .
git commit -m "Prepare FastAPI RAG app for deployment"
git push origin main
```

### Step 2: Create a new Render Web Service
In Render:
1. Log in
2. Click `New +`
3. Choose `Web Service`
4. Connect your GitHub repo
5. Select the repository

### Step 3: Configure the service

#### Build command
```bash
pip install -r requirements.txt
```

#### Start command
```bash
uvicorn app.main:app --host 0.0.0.0 --port 10000
```

### Step 4: Add environment variables in Render
Add these in the Render dashboard:
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `PINECONE_DIMENSION=768`
- `GROQ_API_KEY`
- `GROQ_MODEL_NAME=llama-3.1-8b-instant`
- `WHATSAPP_TOKEN`
- `DATA_DIR=data`
- `EMBEDDING_MODEL_NAME=BAAI/bge-base-en-v1.5`

### Step 5: Deploy
Render will:
1. install dependencies
2. start the FastAPI app
3. expose a public URL

### Step 6: Access the deployed API
Your app will be available at:
```text
https://your-app.onrender.com
```

Swagger UI will be at:
```text
https://your-app.onrender.com/docs
```

## 11. How To Deploy To Azure App Service (Linux)

### Expected ZIP layout
Azure should receive a ZIP whose root contains these items directly:
- `app/`
- `requirements.txt`
- `main.py` optional, but fine to keep

Do not ZIP the parent folder itself. The ZIP should not look like:
- `CHAR.A.I/app/`

It should look like:
- `app/`
- `requirements.txt`

### App entrypoint
Your FastAPI app is already exposed as `app` in [app/main.py](app/main.py#L26), so Azure should start:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If you prefer a wrapper script, use [startup.sh](startup.sh) and set the Azure Startup Command to:
```bash
bash startup.sh
```

### Required Azure settings
Add this app setting so Azure routes traffic to the same port your app binds to:
- `WEBSITES_PORT=8000`

### Why Oryx may fall back to the default placeholder
Common causes are:
- `requirements.txt` is not at the ZIP root
- the app was zipped with an extra parent folder
- the startup command was not set, so Azure used the default site from `/opt/defaultsite`
- FastAPI or Uvicorn were missing from `requirements.txt`

### Files to keep in place
Keep these files at the repo root for deployment:
- `requirements.txt`
- `main.py` 
- `startup.sh` if you want a script-based startup command

### Minimal Azure checklist
1. ZIP the contents of the repo root, not the parent folder.
2. Confirm `app/main.py` defines `app = FastAPI(...)`.
3. Set the Startup Command to `uvicorn app.main:app --host 0.0.0.0 --port 8000` or `bash startup.sh`.
4. Set `WEBSITES_PORT=8000`.
5. Redeploy and check `/docs`.

## Production Notes

### About the `data/` folder on Render
Render containers can be ephemeral.
That means local files may not persist the same way they do on your laptop.

For simple testing, you can include files in the repo under `data/`.
For serious production usage, you usually want persistent storage or a separate ingestion source.

### Minimal production checklist
- repo pushed to GitHub
- valid Pinecone index configured
- valid Groq API key configured
- files available in `data/`
- app starts successfully
- `/docs` is reachable
- `/admin/ingest` works
- `/webhook` returns answers

## Quick Start Summary

### Local run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Open dashboard
```text
http://127.0.0.1:8000/docs
```

### Add data
- Put `.txt`, `.md`, `.pdf` files into `data/`

### Ingest data
- Restart serverx 
- or call `POST /admin/ingest`

### Ask a question
Use `POST /webhook` with:
```json
{
  "user": "dev",
  "message": "your question"
}
```
