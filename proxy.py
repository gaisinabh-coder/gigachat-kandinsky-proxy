from flask import Flask, request, jsonify
import requests, uuid, time, json

app = Flask(__name__)

# ---------- GigaChat ----------
AUTH_KEY = "MDE5OTcwM2YtZmRkNC03ODFjLThhZDEtMjYzYmFhMDY3MDMxOmY4MTlhMGUxLTFhYmUtNGUwMS04NzYwLTdmMjExNDE4YzUxMg=="     # Base64(ClientID:ClientSecret)
SCOPE = "GIGACHAT_API_PERS"            # или "GIGACHAT_API_CORP"

def get_gigachat_token():
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {AUTH_KEY}"
    }
    data = {"scope": SCOPE}
    r = requests.post(url, headers=headers, data=data, verify=False)
    r.raise_for_status()
    return r.json()["access_token"]

@app.route("/chat", methods=["POST"])
def chat():
    token = get_gigachat_token()
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    r = requests.post(url, headers=headers, json=request.json, verify=False)
    return jsonify(r.json())


# ---------- Kandinsky ----------
KANDINSKY_URL = "https://api-key.fusionbrain.ai/"
KANDINSKY_KEY = "0A427A73AF77E3A6EE1E87C70E42018B"          # из кабинета FusionBrain
KANDINSKY_SECRET = "FB14249C0AA9E01A9A5034708EB0B8C8"    # из кабинета FusionBrain

def get_pipeline_id():
    headers = {
        "X-Key": f"Key {KANDINSKY_KEY}",
        "X-Secret": f"Secret {KANDINSKY_SECRET}"
    }
    r = requests.get(KANDINSKY_URL + "key/api/v1/pipelines", headers=headers)
    r.raise_for_status()
    data = r.json()
    return data[0]["id"]   # первый активный pipeline

@app.route("/kandinsky", methods=["POST"])
def kandinsky():
    query = request.json.get("query", "кот в очках")
    width = request.json.get("width", 512)
    height = request.json.get("height", 512)

    pipeline_id = get_pipeline_id()

    headers = {
        "X-Key": f"Key {KANDINSKY_KEY}",
        "X-Secret": f"Secret {KANDINSKY_SECRET}"
    }

    params = {
        "type": "GENERATE",
        "numImages": 1,
        "width": width,
        "height": height,
        "generateParams": {"query": query}
    }

    files = {
        "pipeline_id": (None, pipeline_id),
        "params": (None, json.dumps(params), "application/json")
    }

    r = requests.post(KANDINSKY_URL + "key/api/v1/pipeline/run",
                      headers=headers, files=files)
    r.raise_for_status()
    task = r.json()
    task_id = task["uuid"]
 # иногда Kandinsky возвращает пустое тело → пробуем текст
    try:
        task = r.json()
    except Exception:
        return jsonify({"error": "Bad response from Kandinsky", "text": r.text}), 500

    task_id = task.get("uuid")
    if not task_id:
        return jsonify({"error": "No task id", "response": task}), 500
    # Ждём результат
    for _ in range(20):  # до 20 попыток по 3 сек
        time.sleep(3)
        status = requests.get(KANDINSKY_URL + f"key/api/v1/pipeline/status/{task_id}",
                              headers=headers)
        status.raise_for_status()
        data = status.json()
        if data["status"] == "DONE":
            return jsonify(data["result"]["files"])  # base64 картинка
    return jsonify({"error": "Timeout waiting for result"}), 504
# папка для файлов
UPLOAD_FOLDER = "files"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    img_b64 = data.get("image")
    if not img_b64:
        return jsonify({"error": "no image"}), 400
    img_bytes = base64.b64decode(img_b64)
    filename = f"{uuid.uuid4()}.png"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    with open(filepath, "wb") as f:
        f.write(img_bytes)
    file_url = f"{request.host_url}files/{filename}"
    return jsonify({"url": file_url})

@app.route("/files/<path:filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, mimetype="image/png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)



