import base64
import os

from langchain.chat_models import ChatOpenAI
from langchain.schema.messages import HumanMessage
from langgraph.graph import StateGraph
from dotenv import load_dotenv
import openai

load_dotenv()

openai.api_key = os.environ['OPENAI_API_KEY']

# ---- State Definition ----
from typing import TypedDict

FRAMES = []

class ImageSummaryState(TypedDict):
    image_path: str
    summary: str

# ---- Model ----
llm = ChatOpenAI(model="gpt-4o", temperature=0.3)

# ---- Image Summarization Node ----
def summarize_image(state: ImageSummaryState) -> ImageSummaryState:
    with open(state["image_path"], "rb") as f:
        # b64 = base64.b64encode(f.read()).decode("utf-8")
        summarize_png(f.read())

def summarize_png(img):
    b64 = base64.b64encode(img).decode("utf-8")
    message = HumanMessage(content=[
        {"type": "text", "text": "Describe this image concisely."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
    ])
    response = llm.invoke([message])
    print(response.content)
    return {"summary": response.content}

# ---- LangGraph ----
builder = StateGraph(ImageSummaryState)
builder.add_node("summarize", summarize_image)
builder.set_entry_point("summarize")
builder.set_finish_point("summarize")
graph = builder.compile()

# ---- Run ----
if __name__ == "__main__":
    result = graph.invoke({"image_path": "shutterstock_2096695486-scaled-3375302074.jpg"})
    print("Summary:", result["summary"])
