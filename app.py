from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from clients.brain_client import ask_brain
from clients.service_client import translate_en_to_ru, translate_ru_to_en
from clients.url_utils import join_url
from contracts.context_contract import ContextContract
from logger import WebSocketLogger
import config
import httpx
import json


app = FastAPI()
templates = Jinja2Templates(directory="templates")
logger = WebSocketLogger(websocket)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
    )


@app.get("/api/status")
async def api_status():
    async def check(base_url):
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.get(join_url(base_url, config.MODELS_ENDPOINT))
                return response.status_code == 200
        except Exception:
            return False

    return {
        "brain": await check(config.BRAIN_API_BASE),
        "service": await check(config.SERVICE_API_BASE),
    }


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_text_ru = message_data.get("text", "").strip()

            if not user_text_ru:
                continue

            if config.BYPASS_BRAIN:

                response_ru = await ask_brain(user_text_ru)
                await websocket.send_json({
                    "type": "message",
                    "text": response_ru,
                })
                continue

            # Step 1: service node translates the Russian chat input to English.
            await logger.log_before_hook(f"Sending RU input to service translator: '{user_text_ru}'")

            text_en = await translate_ru_to_en(user_text_ru)

            if text_en.startswith("[TRANSLATION_ERROR"):
                await logger.log_before_hook(f"RU -> EN translation failed. Using original input. Details: {text_en}")
                text_en = user_text_ru
                await logger.log_before_hook(f"Service translator returned EN text: '{text_en}'")

            # Step 2: build brain payload

            if config.USE_SERVICE_AS_BRAIN:
                brain_payload = text_en
            else:
                await logger.log_service_as_brain(f"Service translator returned EN text: '{text_en}'")
                context_contract = ContextContract(
                    user_input=text_en,
                    compressed_history="",
                    system_state="ACTIVE"
                )
                brain_payload = context_contract.to_xml()

            await logger.log_payload(brain_payload[:500])

            brain_response_en = await ask_brain(brain_payload)

            if (
                brain_response_en.startswith("[QWEN_ERROR")
                or brain_response_en.startswith("[SERVICE_BRAIN_ERROR")
            ):
                if config.USE_SERVICE_AS_BRAIN:
                    logger.log_service_as_brain(f"Brain request failed: {brain_response_en}")
                else:
                    logger.log_brain(f"Brain request failed: {brain_response_en}")

                brain_response_en = (
                    "Temporary fallback response. "
                    f"Received payload: '{text_en}'"
                )

            if config.USE_SERVICE_AS_BRAIN:
                logger.log_service_as_brain(f"Brain returned raw EN answer: '{brain_response_en}'")
            else:
                logger.log_brain(f"Brain returned raw EN answer: '{brain_response_en}'")

            # Step 3: service node translates the English brain answer back to Russian.
            logger.log_after_hook("Sending EN brain answer to service translator for RU output.")

            brain_response_ru = await translate_en_to_ru(brain_response_en)

            if brain_response_ru.startswith("[TRANSLATION_ERROR"):
                logger.log_after_hook("EN -> RU translation failed. "
                                      f"Showing raw EN brain answer. Details: {brain_response_ru}")

                brain_response_ru = brain_response_en

            # Step 4: return the Russian answer to chat.
            await websocket.send_json({
                "type": "message",
                "text": brain_response_ru,
            })

            logger.log_system("Processing cycle complete. Pipeline is waiting for the next chat message.)

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"Error with WebSocket session: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
