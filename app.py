from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from clients.brain_client import ask_brain
from clients.service_client import translate_en_to_ru, translate_ru_to_en
import json
import asyncio
import config
import httpx
from contracts.context_contract import ContextContract
from clients.url_utils import join_url

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


@app.get("/api/status")
async def api_status():

    async def check(base_url):
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                r = await client.get(join_url(base_url, config.MODELS_ENDPOINT))
                return r.status_code == 200
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

            # --- ШАГ 1: ПЕРЕВОД НА АНГЛИЙСКИЙ (BEFORE_HOOK на GTX 1070) ---
            await websocket.send_json({
                "type": "log", 
                "tag": "[BEFORE_HOOK]", 
                "message": f"Отправка на service node. Исходный текст: '{user_text_ru}'"
            })
            
            if config.USE_SERVICE_AS_BRAIN:
                text_en = user_text_ru
                await websocket.send_json({
                    "type": "log",
                    "tag": "[BEFORE_HOOK]",
                    "message": "Service brain mode active. Translation bridge skipped."
                })
            else:
                text_en = await translate_ru_to_en(user_text_ru)

                if text_en.startswith("[TRANSLATION_ERROR"):
                    await websocket.send_json({
                        "type": "log",
                        "tag": "[BEFORE_HOOK]",
                        "message": f"Translation failed. Using original user text. Details: {text_en}"
                    })
                    text_en = user_text_ru
                
                await websocket.send_json({
                    "type": "log", 
                    "tag": "[BEFORE_HOOK]", 
                    "message": f"Gemma вернула перевод: '{text_en}'"
                })

            # --- ШАГ 2: СИМУЛЯЦИЯ РАБОТЫ QWEN (BRAIN_NODE на RTX 3080 Ti) ---
            await websocket.send_json({
                "type": "log", 
                "tag": "[BRAIN_NODE]", 
                "message": "Формирование XML Контракта. Изолированная обработка..."
            })
            
            # Эмулируем задержку "мыслительного" процесса Большого Мозга
            await asyncio.sleep(1.0) 
            
            # Временный фиктивный ответ Мозга на английском
            contract = ContextContract(
                user_input=text_en,
                original_user_input=user_text_ru,
                compressed_history="",
                system_state="ACTIVE"
            )

            contract_xml = contract.to_xml()
            await websocket.send_json({
                "type": "log",
                "tag": "[CONTRACT]",
                "message": contract_xml[:500]
            })

            brain_route = (
                "service node fallback"
                if config.USE_SERVICE_AS_BRAIN
                else "primary brain node"
            )

            await websocket.send_json({
                "type": "log",
                "tag": "[BRAIN_NODE]",
                "message": (
                    f"Отправка brain payload в {brain_route}. "
                    f"service_timeout={getattr(config, 'SERVICE_BRAIN_TIMEOUT', 90.0)}s, "
                    f"service_max_tokens={getattr(config, 'SERVICE_BRAIN_MAX_TOKENS', 512)}"
                )
            })

            brain_response_en = await ask_brain(contract_xml)

            if (
                brain_response_en.startswith("[QWEN_ERROR")
                or brain_response_en.startswith("[SERVICE_BRAIN_ERROR")
            ):

                await websocket.send_json({
                    "type": "log",
                    "tag": "[BRAIN_NODE]",
                    "message": f"Brain request failed: {brain_response_en}"
                })

                brain_response_en = (
                    f"Temporary fallback response. "
                    f"Received payload: '{text_en}'"
                )
            
            await websocket.send_json({
                "type": "log", 
                "tag": "[BRAIN_NODE]", 
                "message": f"Qwen выдал сырой ответ: '{brain_response_en}'"
            })

            if config.USE_SERVICE_AS_BRAIN:
                await websocket.send_json({
                    "type": "log",
                    "tag": "[AFTER_HOOK]",
                    "message": "Service brain already answered in RU. Reverse translation skipped."
                })
                brain_response_ru = brain_response_en
            else:
                # --- ШАГ 3: ОБРАТНЫЙ ПЕРЕВОД (AFTER_HOOK на GTX 1070) ---
                await websocket.send_json({
                    "type": "log", 
                    "tag": "[AFTER_HOOK]", 
                    "message": "Валидация синтаксиса успешна. Запрос обратного перевода в RU..."
                })
                
                brain_response_ru = await translate_en_to_ru(brain_response_en)

                if brain_response_ru.startswith("[TRANSLATION_ERROR"):
                    await websocket.send_json({
                        "type": "log",
                        "tag": "[AFTER_HOOK]",
                        "message": (
                            "Reverse translation failed. "
                            f"Showing raw brain answer. Details: {brain_response_ru}"
                        )
                    })
                    brain_response_ru = brain_response_en

            # --- ШАГ 4: ОТПРАВКА В ЧАТ ХОСТУ ---
            await websocket.send_json({
                "type": "message",
                "text": brain_response_ru
            })
            
            await websocket.send_json({
                "type": "log", 
                "tag": "[SYSTEM]", 
                "message": "Цикл обработки завершен. Пайплайн в режиме ожидания."
            })

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"Error with WebSocket session: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
