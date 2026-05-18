from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from clients.brain_client import ask_brain
from clients.service_client import translate_en_to_ru, translate_ru_to_en
from clients.url_utils import join_url

from logger import WebSocketLogger

import config
import httpx
import json

from memory.runtime_state import runtime_state

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // config.TOKEN_ESTIMATION_DIVISOR)

async def send_telemetry(websocket: WebSocket):
    await websocket.send_json({
        "type": "telemetry",
        "brain": runtime_state.brain,
        "service": runtime_state.service,
    })

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
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
    await send_telemetry(websocket)
    logger = WebSocketLogger(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_text_ru = message_data.get("text", "").strip()

            if not user_text_ru:
                continue

            if config.BYPASS_BRAIN:

                response_ru = await ask_brain(user_text_ru)

                runtime_state.brain["model"] = config.SERVICE_MODEL_UID

                runtime_state.brain["used_tokens"] = estimate_tokens(
                    user_text_ru + response_ru
                )

                runtime_state.brain["max_tokens"] = (
                    config.SERVICE_CONTEXT_WINDOW
                )

                await send_telemetry(websocket)

                await websocket.send_json({
                    "type": "message",
                    "text": response_ru,
                })

                continue

            # Step 1: service node translates the Russian chat input to English.
            await logger.log_before_hook(f"Sending RU input to service translator: '{user_text_ru}'")

            text_en = await translate_ru_to_en(user_text_ru)

            runtime_state.service["model"] = config.SERVICE_MODEL_UID
            runtime_state.service["used_tokens"] = estimate_tokens(user_text_ru + text_en)
            runtime_state.service["max_tokens"] = config.SERVICE_CONTEXT_WINDOW

            await send_telemetry(websocket)

            if text_en.startswith("[TRANSLATION_ERROR"):
                await logger.log_before_hook(f"RU -> EN translation failed. Using original input. Details: {text_en}")
                text_en = user_text_ru

            await logger.log_before_hook(f"Service translator returned EN text: '{text_en}'")

            await logger.log_service(
               f"Service translator returned EN text: '{text_en}'"
            )


            try:
                brain_response_en = await ask_brain(text_en)
                print("BRAIN RAW RESPONSE:", brain_response_en)
                runtime_state.brain["model"] = config.BRAIN_MODEL_UID
                runtime_state.brain["used_tokens"] = estimate_tokens(text_en + brain_response_en)
                runtime_state.brain["max_tokens"] = config.BRAIN_CONTEXT_WINDOW

                await send_telemetry(websocket)

            except Exception as e:

                runtime_state.brain["model"] = "OFFLINE"

                await send_telemetry(websocket)

                await logger.log_error(str(e))

                await websocket.send_json({
                    "type": "error",
                    "source": "brain",
                    "text": str(e),
                })

                continue

            if config.USE_SERVICE_AS_BRAIN:
                await logger.log_service_as_brain(f"Brain returned raw EN answer: '{brain_response_en}'")
            else:
                await logger.log_brain(f"Brain returned raw EN answer: '{brain_response_en}'")

            # Step 3: service node translates the English brain answer back to Russian.
            await logger.log_after_hook("Sending EN brain answer to service translator for RU output.")

            brain_response_ru = await translate_en_to_ru(brain_response_en)

            if brain_response_ru.startswith("[TRANSLATION_ERROR"):
                await logger.log_after_hook("EN -> RU translation failed. "
                                          f"Showing raw EN brain answer. Details: {brain_response_ru}")

                brain_response_ru = brain_response_en

            # Step 4: return the Russian answer to chat.
            await websocket.send_json({
                "type": "message",
                "text": brain_response_ru,
            })

            await logger.log_system("Processing cycle complete. Pipeline is waiting for the next chat message.")

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"Error with WebSocket session: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
