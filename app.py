from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
import requests
import base64
import json
import re

API_URL = "http://10.250.12.5:8105/v1/chat/completions"
API_KEY = "token-abc123"
MODEL = "Qwen/Qwen3-VL-8B-Instruct-FP8"

app = FastAPI(
    title="HMEL Card Reader Service",
    version="1.0.1",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.get("/")
def root():
    return {
        "service": "HMEL Card Reader Service",
        "version": "1.0.1",
        "status": "operational",
        "environment": "staging",
        "docs_url": "/docs"
    }


# 🔹 Updated to ensure 'string' appears in request body
class ImagePayload(BaseModel):
    image_base64: str = Field(
        ...,
        title="Image Base64 String",
        description="Paste your base64 encoded image here as a plain string.",
        example="string"
    )


def clean_json_markdown(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.lstrip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.rstrip("`")
    return text.strip()


@app.get("/status")
def status():
    return {"status": "API is working", "service": "extractor", "code": 200}


@app.post("/extract")
def extract_details(payload: ImagePayload):

    # Clean: remove prefix "data:image/png;base64,"
    match = re.match(r"data:image\/[a-zA-Z]+;base64,(.*)", payload.image_base64)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Invalid base64 image format. Must start with data:image/...;base64,"
        )

    clean_b64 = match.group(1)

    prompt_text = """
Extract all possible details from the business card image.

Return ONLY valid JSON in the EXACT structure below:

{
    "extracted_info": {
        "name": [],
        "email": [],
        "phone": [],
        "designation": "",
        "company_name": "",
        "website": "",
        "address": "",
        "additional_info": {
            "category": [],
            "other": []
        }
    }
}

Rules:
- name, email, phone, category, other → arrays (even if one item)
- "category" = business classification such as: fire safety, govt approved, certifications, etc.
- "other" = ANY additional text found on the card not part of the main fields.
- Do NOT add fields outside this structure.
- Missing values must be empty "" or empty [].
- Preserve original spellings and text.
"""

    payload_data = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{clean_b64}"}}
                ]
            }
        ],
        "max_tokens": 1024,
        "temperature": 0.0
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    response = requests.post(API_URL, headers=headers, json=payload_data)

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="LLM API Error: " + response.text)

    resp_json = response.json()

    if "choices" not in resp_json:
        raise HTTPException(status_code=500, detail="Invalid LLM response: " + response.text)

    result_text = resp_json["choices"][0]["message"]["content"]
    cleaned_text = clean_json_markdown(result_text)

    # Convert JSON
    try:
        result_json = json.loads(cleaned_text)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to parse JSON", "raw_output": cleaned_text}
        )

    return result_json

@app.post("/direct-markdown")
async def extract_text_markdown(file: UploadFile = File(...)):
    """
    Extract ALL text from an uploaded image and return the result in MARKDOWN format.
    No JSON structure, no predefined fields.
    """

    # Read the uploaded image
    image_bytes = await file.read()

    # Encode image to base64
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    # Prompt specifically for RAW TEXT but formatted as Markdown
    prompt_text = """
Extract ALL readable text from this image.

Return the output **ONLY in Markdown format**.

Rules:
- Keep the exact text as visible in the image
- Preserve line breaks
- No additional JSON
- No extra explanation
- Only return markdown text
"""

    # LLM request payload
    payload_data = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                    }
                ]
            }
        ],
        "max_tokens": 600,
        "temperature": 0.0
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    # Call LLM
    response = requests.post(API_URL, headers=headers, json=payload_data)

    if response.status_code != 200:
        raise HTTPException(500, "LLM API Error: " + response.text)

    resp_json = response.json()

    if "choices" not in resp_json:
        raise HTTPException(500, "Invalid LLM response: " + response.text)

    markdown_text = resp_json["choices"][0]["message"]["content"]

    # Return markdown
    return {"markdown": markdown_text.strip()}

