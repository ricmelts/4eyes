import os
import uuid
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

from langchain.chat_models import ChatOpenAI
from langchain.schema.messages import HumanMessage
from supabase import create_client

from PIL import Image, ImageSequence
import io

MAX_MB = 50  # Supabase storage upload limit

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

def compress_gif_bytes(gif_bytes: bytes, max_width: int = 400, fps: int = 10) -> bytes:
    input_image = Image.open(io.BytesIO(gif_bytes))

    # Extract and resize frames
    frames = []
    duration_per_frame = max(1, int(1000 / fps))  # in milliseconds
    for frame in ImageSequence.Iterator(input_image):
        frame = frame.convert("P")  # ensure palette mode
        if frame.width > max_width:
            w_percent = max_width / float(frame.width)
            h_size = int((float(frame.height) * float(w_percent)))
            frame = frame.resize((max_width, h_size), Image.LANCZOS)
        frames.append(frame)

    # Save the new GIF
    output_bytes_io = io.BytesIO()
    frames[0].save(
        output_bytes_io,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=duration_per_frame,
        loop=0,
        optimize=True
    )

    return output_bytes_io.getvalue()

def upload_gif_to_supabase(gif_bytes: bytes, file_id: str) -> str:
    # Compress if too large
    if len(gif_bytes) > MAX_MB * 1024 * 1024:
        print(f"⚠️ GIF is {len(gif_bytes) / (1024*1024):.2f}MB — compressing...")
        gif_bytes = compress_gif_bytes(gif_bytes)
        print(f"✅ Compressed to {len(gif_bytes) / (1024*1024):.2f}MB")

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


def send_gif_to_supabase_pipeline(gif_bytes: bytes) -> dict:
    file_id = f"{uuid.uuid4()}.gif"
    file_path = f"{BUCKET_NAME}/{file_id}"

    print("🔍 Summarizing GIF...")
    summary = summarize_gif(gif_bytes)
    print("🧠 Summary:", summary)

    print("📤 Uploading to Supabase Storage...")
    public_url = upload_gif_to_supabase(gif_bytes, file_id)
    print("🔗 Public URL:", public_url)

    print("📝 Storing metadata...")
    store_metadata(file_path=file_path, public_url=public_url, summary=summary)

    print("✅ All done.")
    return {
        "summary": summary,
        "public_url": public_url,
        "file_path": file_path
    }


# ---- Example Call ----
if __name__ == "__main__":
    from pathlib import Path

    gif_path = "output.gif"
    gif_bytes = Path(gif_path).read_bytes()
    result = send_gif_to_supabase_pipeline(gif_bytes)
    print(result)
