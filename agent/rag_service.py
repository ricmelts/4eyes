import os
import tempfile
from typing import Dict, Any, Callable
from dotenv import load_dotenv
from viaRAG.client import ViaRAGClient

load_dotenv()

# ---- Client ----
client = ViaRAGClient(os.environ["VIARAG_KEY"])


def upload_single_gif_summary(
        file_path: str,
        summary: str,
        # format_fn: Callable[[str, str], str]
) -> Dict[str, Any]:
    """
    Uploads a single GIF summary to ViaRAG as a text document.

    :param file_path: Path to the GIF (used as metadata)
    :param summary: Description of the GIF
    :param format_fn: Function to control how the summary is formatted in the text file
    :return: Upload response from ViaRAG
    """
    # Write summary to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
        # f.write(format_fn(file_path, summary) + "\n")
        f.write(summary)
        temp_path = f.name

    # Upload
    try:
        metadata = {"gif_path": file_path}
        return client.upload_document(
            file_path=temp_path,
            metadata=metadata,
            chunking_config=None
        )
    finally:
        os.remove(temp_path)


# ---- Example Format Function ----
def default_format_fn(file_path: str, summary: str) -> str:
    return f"{file_path}:\n{summary}"


# ---- Example Usage ----
if __name__ == "__main__":
    resp = upload_single_gif_summary(
        file_path="gifs/example123.gif",
        summary="A cat jumps onto a table and knocks over a cup.",
        format_fn=default_format_fn
    )
    print("✅ Upload complete:", resp)
