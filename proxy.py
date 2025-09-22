from flask import Flask, request, jsonify
import requests, uuid

app = Flask(__name__)

# 🔹 Подставь сюда свой ключ авторизации Base64(ClientID:ClientSecret)
AUTH_KEY = "MDE5OTcwM2YtZmRkNC03ODFjLThhZDEtMjYzYmFhMDY3MDMxOmY4MTlhMGUxLTFhYmUtNGUwMS04NzYwLTdmMjExNDE4YzUxMg=="

# 🔹 Выбери scope, который у тебя есть (обычно персональный):
SCOPE = "GIGACHAT_API_PERS"   # или "GIGACHAT_API_CORP"

# ---------- Получение токена ----------
def get_token():
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {AUTH_KEY}"
    }
    data = {"scope": SCOPE}
    r = requests.post(url, headers=headers, data=data, verify=False)  # verify=False → не ругается на сертификат
    r.raise_for_status()
    return r.json()["access_token"]

# ---------- GigaChat (тексты) ----------
@app.route("/chat", methods=["POST"])
def chat():
    token = get_token()
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    r = requests.post(url, headers=headers, json=request.json, verify=False)
    return jsonify(r.json())

# ---------- Kandinsky (картинки) ----------
@app.route("/kandinsky", methods=["POST"])
def kandinsky():
    token = get_token()
    # ⚠️ Подставь сюда свой эндпоинт запуска генерации (из кабинета разработчика)
    url = "https://api-key.fusionbrain.ai/key/api/v1/99d833d6-fec0-44fd-a1c2-35d6bf96b5c2"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    r = requests.post(url, headers=headers, json=request.json, verify=False)
    return jsonify(r.json())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
