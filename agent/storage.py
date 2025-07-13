import os
import uuid
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

from langchain.chat_models import ChatOpenAI
from langchain.schema.messages import HumanMessage
from supabase import create_client

load_dotenv()

# ---- Supabase Config ----
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BUCKET_NAME = "gifs"

# ---- Langchain GPT-4o LLM ----
llm = ChatOpenAI(model="gpt-4o", temperature=0.3)

# ---- Supabase Client ----
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def summarize_gif(gif_bytes: bytes) -> str:
    b64 = base64.b64encode(gif_bytes).decode("utf-8")
    message = HumanMessage(content=[
        {"type": "text", "text": "This is an animated GIF. Please summarize the animation as if you watched a short silent video."},
        {"type": "image_url", "image_url": {"url": f"data:image/gif;base64,{b64}"}}
    ])
    response = llm.invoke([message])
    return response.content


def upload_gif_to_supabase(gif_bytes: bytes, file_id: str) -> str:
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{file_id}"

    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "image/gif"
    }

    response = requests.post(upload_url, headers=headers, data=gif_bytes)

    if response.status_code in [200, 201]:
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{file_id}"
    else:
        raise Exception(f"Upload failed: {response.status_code} - {response.text}")


def store_metadata(file_path: str, public_url: str, summary: str):
    response = supabase.table("gif_metadata").insert({
        "file_path": file_path,
        "public_url": public_url,
        "summary": summary,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

    if response.get("status_code") not in [200, 201]:
        raise Exception(f"Metadata insert failed: {response}")
    return response


# ---- Main Routine ----
if __name__ == "__main__":
    from pathlib import Path

    gif_path = "example.gif"
    gif_bytes = Path(gif_path).read_bytes()
    file_id = f"{uuid.uuid4()}.gif"

    print("Summarizing GIF...")
    summary = summarize_gif(gif_bytes)
    print("Summary:", summary)

    print("Uploading to Supabase...")
    public_url = upload_gif_to_supabase(gif_bytes, file_id)
    print("Public URL:", public_url)

    print("Saving metadata...")
    store_metadata(file_path=f"{BUCKET_NAME}/{file_id}", public_url=public_url, summary=summary)

    print("✅ Done.")
