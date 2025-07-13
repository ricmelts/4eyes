import base64
import io
import os
import uuid
from datetime import datetime

import requests
from PIL import Image, ImageSequence
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.schema.messages import HumanMessage, SystemMessage
from supabase import create_client
import rag_service

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
        {"type": "text", "text": "Watch this animated GIF as if it is a short silent video."
                                 "Describe exactly what happens with clear and detailed visual storytelling."
                                 "Imagine you are reminding someone of a moment they saw before."
                                 "Be specific and concrete."
                                 "Focus on what is actually shown without adding poetic language or nostalgia."},
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
        print(f"⚠️ GIF is {len(gif_bytes) / (1024 * 1024):.2f}MB — compressing...")
        gif_bytes = compress_gif_bytes(gif_bytes)
        print(f"✅ Compressed to {len(gif_bytes) / (1024 * 1024):.2f}MB")

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
        "created_at": datetime.utcnow().isoformat()  # also fixes your UTC warning
    }).execute()

    if not response.data:
        raise Exception(f"Metadata insert failed: {response}")

def generate_hypotheticals(summary: str, k: int = 3) -> list[str]:
    sys_prompt = SystemMessage(
        content=(
            f"You are a system designed to optimize content for a Retrieval-Augmented Generation (RAG) pipeline, like HyPE.\n\n"
            f"Your task is to generate exactly {k} distinct hypothetical user questions that could plausibly retrieve the following summary.\n"
            f"The goal is **not** to test recall or trivia. Instead, generate questions someone might ask when trying to remember or find this moment again.\n\n"
            f"The tone should be casual or vague — like how a person might search from memory:\n"
            f"Examples:\n"
            f"- what was that cafe I went to\n"
            f"- show me the time I played basketball\n\n"
            f"Output only the {k} questions as a numbered list (e.g., '1. ...'). No extra commentary or explanation."
        )
    )
    user_prompt = HumanMessage(content=summary)

    response = llm.invoke([sys_prompt, user_prompt])
    text = response.content

    # Extract clean question list
    lines = text.strip().splitlines()
    questions = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit() or line.startswith("-"):
            line = line.lstrip("0123456789.-) ").strip()
        questions.append(line)

    if len(questions) != k:
        raise ValueError(f"Expected {k} questions, got {len(questions)}: {questions}")

    return questions

def add_to_vector_store(file_path: str, summary: str):
    hypos = generate_hypotheticals(summary)

    for hypo in hypos:
        rag_service.upload_single_gif_summary(file_path, hypo)

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

    print("Adding to vector store...")
    add_to_vector_store(file_path=file_path, summary=summary)

    print("✅ All done.")
    return {
        "summary": summary,
        "public_url": public_url,
        "file_path": file_path
    }


# ---- Example Call ----
if __name__ == "__main__":
    from pathlib import Path

    # gif_path = "output_20250713_001810.gif"
    # gif_bytes = Path(gif_path).read_bytes()
    # result = send_gif_to_supabase_pipeline(gif_bytes)
    # print(result)

    folder_path = Path("test_gifs")

    for gif_path in folder_path.glob("*.gif"):
        print(f"📂 Processing {gif_path.name}...")

        gif_bytes = gif_path.read_bytes()
        try:
            result = send_gif_to_supabase_pipeline(gif_bytes)
            print("✅ Success:", result)
        except Exception as e:
            print(f"❌ Failed for {gif_path.name}: {e}")