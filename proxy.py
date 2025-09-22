# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, send_from_directory
import os, json, time, uuid, base64, requests
from typing import Optional, List

app = Flask(__name__)

# ====== НАСТРОЙКИ (через переменные окружения) ======
# Render → Dashboard → Environment → добавить переменные

# --- GigaChat ---
GIGACHAT_CLIENT_ID     = os.getenv("GIGACHAT_CLIENT_ID", "")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET", "")
# PERS (физлица) / B2B / CORP — что у вас реально выдано
GIGACHAT_SCOPE         = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
# Модель, если не знаете — оставьте "GigaChat"
GIGACHAT_MODEL         = os.getenv("GIGACHAT_MODEL", "GigaChat")

# --- Kandinsky (FusionBrain) ---
FUSION_URL   = os.getenv("FUSION_URL", "https://api-key.fusionbrain.ai/")
FUSION_KEY   = os.getenv("FUSION_KEY", "")      # X-Key:  Key <...>
FUSION_SECRET= os.getenv("FUSION_SECRET", "")   # X-Secret: Secret <...>
# Размер картинки
K_WIDTH  = int(os.getenv("K_WIDTH", "1024"))
K_HEIGHT = int(os.getenv("K_HEIGHT", "1024"))

# --- Telegram (необязательно) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")  # можно оставить пустым

# Папка для статической раздачи файлов
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "files")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ====== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======

def _gigachat_get_token() -> str:
    """
    OAuth2 для GigaChat: POST /api/v2/oauth (Basic auth + scope)
    Документация: https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api
    """
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        raise RuntimeError("GigaChat creds are empty. Set GIGACHAT_CLIENT_ID/SECRET env vars.")

    token_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    rq_uid = str(uuid.uuid4())
    basic = base64.b64encode(f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}".encode("utf-8")).decode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": rq_uid,
        "Authorization": f"Basic {basic}",
    }
    data = {"scope": GIGACHAT_SCOPE}
    resp = requests.post(token_url, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    j = resp.json()
    return j["access_token"]

def gigachat_chat(prompt: str) -> str:
    token = _gigachat_get_token()
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {
        "model": GIGACHAT_MODEL,
        "messages": [
            {"role": "system", "content": "Ты кратко и по делу формируешь подпись к изображению."},
            {"role": "user", "content": prompt}
        ]
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    # Унифицируем: возьмём первый ответ
    # (структура как у /chat/completions — choices[0].message.content)
    return j["choices"][0]["message"]["content"]

def _fusion_headers():
    if not FUSION_KEY or not FUSION_SECRET:
        raise RuntimeError("FusionBrain API creds empty. Set FUSION_KEY/FUSION_SECRET env vars.")
    return {
        "X-Key": f"Key {FUSION_KEY}",
        "X-Secret": f"Secret {FUSION_SECRET}",
    }

def fusion_get_pipeline_id() -> str:
    r = requests.get(FUSION_URL + "key/api/v1/pipelines", headers=_fusion_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    # Берём первый активный пайплайн (обычно Kandinsky)
    return data[0]["id"]

def fusion_run_generate(pipeline_id: str, prompt: str, width: int, height: int) -> str:
    params = {
        "type": "GENERATE",
        "numImages": 1,
        "width": width,
        "height": height,
        "generateParams": {"query": prompt}
    }
    files = {
        "pipeline_id": (None, pipeline_id),
        "params": (None, json.dumps(params), "application/json"),
    }
    r = requests.post(FUSION_URL + "key/api/v1/pipeline/run", headers=_fusion_headers(), files=files, timeout=60)
    r.raise_for_status()
    return r.json()["uuid"]

def fusion_poll_files(task_uuid: str, attempts: int = 30, delay_sec: float = 2.0) -> List[str]:
    """
    Ожидаем статусы, пока не станет DONE. Возвращаем массив base64-строк (files).
    """
    status_url = FUSION_URL + "key/api/v1/pipeline/status/" + task_uuid
    for _ in range(attempts):
        r = requests.get(status_url, headers=_fusion_headers(), timeout=30)
        r.raise_for_status()
        j = r.json()
        if j.get("status") == "DONE":
            result = j.get("result", {})
            files = result.get("files", [])
            if files:
                return files
            raise RuntimeError("Kandinsky DONE but no files in result.")
        elif j.get("status") == "FAIL":
            raise RuntimeError("Kandinsky status FAIL: " + j.get("errorDescription", ""))
        time.sleep(delay_sec)
    raise TimeoutError("Kandinsky polling timed out.")

def save_base64_png(b64_str: str) -> str:
    img_bytes = base64.b64decode(b64_str)
    filename = f"{uuid.uuid4()}.png"
    path = os.path.join(UPLOAD_FOLDER, filename)
    with open(path, "wb") as f:
        f.write(img_bytes)
    return filename

def send_telegram_photo(photo_url: str, caption: str, chat_id: Optional[str] = None) -> dict:
    """
    Отправка фото в Telegram ботом (по желанию).
    Если TELEGRAM_BOT_TOKEN не задан — просто возвращаем {}.
    """
    if not TELEGRAM_BOT_TOKEN:
        return {}
    tgt_chat = chat_id or DEFAULT_CHAT_ID
    if not tgt_chat:
        # нет chat_id — нет отправки
        return {}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    # Телега ограничивает подпись ~1024 символами
    safe_caption = caption[:1024] if caption else ""
    payload = {"chat_id": tgt_chat, "photo": photo_url, "caption": safe_caption}
    r = requests.post(url, data=payload, timeout=30)
    # Не бросаем исключение, просто возвращаем, что ответила Телега
    try:
        return r.json()
    except Exception:
        return {"status_code": r.status_code, "text": r.text}

# ====== HTTP ЭНДПОИНТЫ ======

@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/files/<path:filename>")
def files(filename):
    # Отдаём сохранённые PNG
    return send_from_directory(UPLOAD_FOLDER, filename, mimetype="image/png")

@app.route("/combo", methods=["POST"])
def combo():
    """
    Минимум шагов в Make: один POST на /combo.
    JSON вход:
    {
      "text_prompt": "описание для подписи (или общий промпт)",
      "image_prompt": "описание для картинки (если не задано — берём text_prompt)",
      "chat_id": "...",          # опционально; если задан TELEGRAM_BOT_TOKEN, можно слать прямо из прокси
      "width": 1024,             # опционально
      "height": 1024             # опционально
    }

    Ответ:
    {
      "text": "...",             # подпись от GigaChat
      "image_url": "https://.../files/xxx.png",
      "telegram": {...}          # ответ Telegram, если включена отправка
    }
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        text_prompt = data.get("text_prompt") or data.get("prompt") or ""
        image_prompt = data.get("image_prompt") or text_prompt
        w = int(data.get("width") or K_WIDTH)
        h = int(data.get("height") or K_HEIGHT)
        chat_id = data.get("chat_id")

        if not text_prompt:
            return jsonify({"error": "text_prompt is required"}), 400

        # 1) Текст (GigaChat)
        caption = gigachat_chat(text_prompt)

        # 2) Картинка (Kandinsky / FusionBrain)
        pipeline_id = fusion_get_pipeline_id()
        task_id = fusion_run_generate(pipeline_id, image_prompt, w, h)
        files_b64 = fusion_poll_files(task_id)
        img_b64 = files_b64[0]
        filename = save_base64_png(img_b64)
        img_url = f"{request.host_url}files/{filename}"

        # 3) (Опционально) шлём сразу в Telegram
        tg_resp = send_telegram_photo(img_url, caption, chat_id=chat_id)

        return jsonify({
            "text": caption,
            "image_url": img_url,
            "telegram": tg_resp
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Render ожидает порт из $PORT
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
