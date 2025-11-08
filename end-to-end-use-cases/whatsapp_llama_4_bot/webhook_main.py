# webhook_main.py

import os
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# All WhatsApp + LLM helper functions live here
from webhook_utils import (
    send_message,
    llm_reply_to_text_v2,
    audio_conversion,
    send_audio_message,
    # add handle_image_message here if you implement it in webhook_utils
)

load_dotenv()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

app = FastAPI(title="WhatsApp Webhook App", redirect_slashes=False)


class WhatsAppWebhook(BaseModel):
    object: str | None = None
    entry: list


# This will be exposed as: GET /webhook at the top-level (mounted in main.py)
@app.get("/")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta webhook verification endpoint.

    Meta sends:
      - hub.mode
      - hub.verify_token
      - hub.challenge

    If the verify token matches WHATSAPP_VERIFY_TOKEN,
    we MUST return the challenge as plain text with HTTP 200.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        if not hub_challenge:
            raise HTTPException(status_code=400, detail="Missing challenge")
        # Must be raw string, no JSON wrapper
        return PlainTextResponse(content=hub_challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification failed")


# This will be exposed as: POST /webhook at the top-level (mounted in main.py)
@app.post("/")
async def whatsapp_webhook(payload: WhatsAppWebhook, background_tasks: BackgroundTasks):
    """
    Handle incoming WhatsApp webhook events.
    """
    try:
        if not payload.entry:
            return JSONResponse({"status": "ignored"}, status_code=200)

        change = payload.entry[0].get("changes", [])[0]
        value = change.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return JSONResponse({"status": "no_messages"}, status_code=200)

        message = messages[0]
        user_phone = message.get("from")

        if not user_phone:
            return JSONResponse({"status": "no_from"}, status_code=200)

        msg_type = message.get("type")

        # 1️⃣ Text messages
        if msg_type == "text":
            user_message = message["text"]["body"]
            # Process via your LLM / agent in background
            background_tasks.add_task(
                llm_reply_to_text_v2,
                user_message,
                user_phone,
                None,
                None,
            )

        # 2️⃣ Image messages
        elif msg_type == "image":
            media_id = message["image"]["id"]
            caption = message["image"].get("caption", "") or ""
            # If llm_reply_to_text_v2 can handle image via media_id + "image" flag:
            background_tasks.add_task(
                llm_reply_to_text_v2,
                caption,
                user_phone,
                media_id,
                "image",
            )

        # 3️⃣ Audio messages
        elif msg_type == "audio":
            media_id = message["audio"]["id"]

            async def process_audio():
                # Download + convert incoming audio
                path = await audio_conversion("", media_id, "audio")
                # Send an audio reply back
                await send_audio_message(user_phone, path)

            background_tasks.add_task(process_audio)

        # 4️⃣ Unsupported types
        else:
            background_tasks.add_task(
                send_message,
                user_phone,
                "Received your message, but this bot currently supports text, image, and audio only.",
            )

        return JSONResponse({"status": "ok"}, status_code=200)

    except Exception as e:
        print("Webhook error:", e)
        return JSONResponse(
            {"status": "error", "detail": str(e)},
            status_code=500,
        )
