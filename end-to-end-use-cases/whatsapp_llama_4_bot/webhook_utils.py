import os
import base64
import asyncio
import uuid
import requests
import httpx
from pathlib import Path
from PIL import Image
from dotenv import load_dotenv
from io import BytesIO

load_dotenv()

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MEDIA_URL = "https://graph.facebook.com/v20.0/{media_id}"
BASE_URL = os.getenv("BASE_URL")
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL") or BASE_URL
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def send_message(to: str, text: str):
    if not text:
        print("Error: Message text is empty.")
        return

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        print("Message sent")
    else:
        print(f"Send failed: {response.text}")



async def send_message_async(user_phone: str, message: str):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, send_message, user_phone, message)



        
async def send_audio_message(to: str, file_path: str):
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/media"
    with open(file_path, "rb") as f:
        files = { "file": ("reply.mp3", open(file_path, "rb"), "audio/mpeg")}
        params = {
            "messaging_product": "whatsapp",
            "type": "audio",
            "access_token": ACCESS_TOKEN
        }
        response = requests.post(url, params=params, files=files)

    if response.status_code == 200:
        media_id = response.json().get("id")
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"id": media_id}
        }
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
    else:
        print("Audio upload failed:", response.text)






async def llm_reply_to_text_v2(user_input: str, user_phone: str, media_id: str = None,kind: str = None):
    try:
        # print("inside this function")
        headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json',
    }

        if not AGENT_BASE_URL:
            raise RuntimeError("AGENT_BASE_URL (or BASE_URL) is not configured for LLM calls.")

        json_data = {
            'user_input': user_input,
            'media_id': media_id,
            'kind': kind
        }
        
        async with httpx.AsyncClient() as client:
          response = await client.post(
              f"{AGENT_BASE_URL.rstrip('/')}/llm-response",
              json=json_data,
              headers=headers,
              timeout=60,
          )

          content_type = response.headers.get("content-type", "")
          if "application/json" not in content_type:
              preview = response.text[:200] if response.text else "<empty>"
              print(f"Unexpected content-type from LLM API: {content_type}, preview: {preview}")
              await send_message_async(user_phone, "LLM response was not valid JSON.")
              return

          try:
              response_data = response.json()
          except ValueError as json_err:
              preview = response.text[:200] if response.text else "<empty>"
              print(f"Failed to parse LLM JSON response: {json_err}. Body preview: {preview}")
              await send_message_async(user_phone, "LLM response could not be parsed.")
              return

          if response.status_code == 200 and response_data.get('error') is None:
              message_content = response_data['response']
              if message_content:
                  loop = asyncio.get_running_loop()
                  await loop.run_in_executor(None, send_message, user_phone, message_content)
              else:
                  print("Error: Empty message content from LLM API")
                  await send_message_async(user_phone, "Received empty response from LLM API.")
          else:
              print("Error: Invalid LLM API response", response_data)
              await send_message_async(user_phone, "Failed to process image due to an internal server error.")

    except Exception as e:
        print("LLM error:", e)
        await send_message_async(user_phone, "Sorry, something went wrong while generating a response.")


async def audio_conversion(user_input: str, media_id: str, kind: str = "audio") -> str:
    if kind != "audio":
        raise ValueError("audio_conversion currently supports only 'audio' kind.")

    if not BASE_URL:
        raise RuntimeError("BASE_URL is not configured for audio conversion.")

    request_payload = {
        "user_input": user_input,
        "media_id": media_id,
        "kind": kind,
    }

    url = f"{BASE_URL.rstrip('/')}/llm-response"
    headers = {
        "accept": "audio/mpeg",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, json=request_payload, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"Audio conversion failed with status {response.status_code}: {response.text}")

    content_type = response.headers.get("content-type", "")
    if "audio" not in content_type:
        raise RuntimeError(f"Expected audio response, received content type '{content_type}'. Body: {response.text}")

    output_dir = os.getenv("AUDIO_OUTPUT_DIR", ".")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(output_dir) / f"reply_{uuid.uuid4().hex}.mp3"
    output_path.write_bytes(response.content)

    return str(output_path)