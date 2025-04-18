# <DOCUMENT filename="backend/server.py">
import secrets
import hashlib
import base64
import requests
from flask import Flask, request, redirect, jsonify
from flask_cors import CORS
from config.database import init_db
from routes.clip_routes import clip_bp
from routes.user_routes import user_bp
from routes.workspace_routes import workspace_bp
from routes.published_clip_routes import published_clip_bp
from routes.audio_routes import audio_bp
from routes.script_routes import script_bp
import urllib.parse
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(64)

cors = CORS(app, resources={
    r"/*": {
        "origins": "http://localhost:5173",
        "supports_credentials": True,
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Set-Cookie"]
    }
})

port = os.getenv("PORT") or 4000
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
REDIRECT_URI = "https://server-tiktok-api.onrender.com/callback"
SCOPES = "user.info.basic,video.list"

# Khởi tạo database
init_db()

# Đăng ký các blueprint
app.register_blueprint(clip_bp)
app.register_blueprint(user_bp)
app.register_blueprint(workspace_bp)
app.register_blueprint(published_clip_bp)
app.register_blueprint(audio_bp)
app.register_blueprint(script_bp)

def generate_random_string(length):
    characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
    return ''.join(secrets.choice(characters) for _ in range(length))

def generate_code_challenge_pair():
    code_verifier = generate_random_string(64)
    sha256_hash = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_hash).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge

@app.route("/auth/init/")
def auth_init():
    try:
        code_verifier, code_challenge = generate_code_challenge_pair()
        state = generate_random_string(16)
        
        # Truyền state và code_verifier qua query params
        redirect_uri_with_params = f"{REDIRECT_URI}?stored_state={urllib.parse.quote(state)}&code_verifier={urllib.parse.quote(code_verifier)}"
        
        auth_url = (
            f'https://www.tiktok.com/v2/auth/authorize/?'
            f'client_key={urllib.parse.quote(CLIENT_KEY)}&'
            f'scope={urllib.parse.quote(SCOPES)}&'
            f'response_type=code&'
            f'redirect_uri={urllib.parse.quote(redirect_uri_with_params)}&'
            f'state={urllib.parse.quote(state)}&'
            f'code_challenge={urllib.parse.quote(code_challenge)}&'
            f'code_challenge_method=S256'
        )
        print("Generated auth_url:", auth_url)
        print("Stored state:", state)
        print("Redirect URI with params:", redirect_uri_with_params)
        return jsonify({"auth_url": auth_url})
    except Exception as e:
        print("Error in auth_init:", str(e))
        return jsonify({"error": "Failed to initialize auth"}), 500

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    stored_state = request.args.get("stored_state")
    code_verifier = request.args.get("code_verifier")
    error = request.args.get("error")
    
    print("Callback received:", {"code": code, "state": state, "stored_state": stored_state, "code_verifier": code_verifier, "error": error})
    
    if error:
        print("TikTok error:", error)
        return redirect(f"http://localhost:5173/tiktok-login?error={urllib.parse.quote(error)}")
    
    print("State comparison:", {"received": state, "stored": stored_state})
    if state != stored_state:
        print("State mismatch:", {"received": state, "stored": stored_state})
        return jsonify({"error": "CSRF verification failed"}), 400
    
    if not code_verifier:
        print("Missing code_verifier")
        return jsonify({"error": "Missing code verifier"}), 400

    if not code:
        print("Missing code")
        return jsonify({"error": "Missing code"}), 400

    redirect_uri_with_params = f"{REDIRECT_URI}?stored_state={urllib.parse.quote(stored_state)}&code_verifier={urllib.parse.quote(code_verifier)}"
    access_token = get_access_token(code, code_verifier, redirect_uri_with_params)
    if access_token:
        print("Access token obtained:", access_token)
        return redirect(f"http://localhost:5173/tiktok-stats?access_token={urllib.parse.quote(access_token)}")
    else:
        print("Failed to obtain access token")
        return redirect("http://localhost:5173/tiktok-login?error=failed_to_get_token")

def get_access_token(code, code_verifier, redirect_uri):
    url = 'https://open.tiktokapis.com/v2/oauth/token/'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    payload = {
        'client_key': CLIENT_KEY,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri,
        'code_verifier': code_verifier
    }
    print("Token request payload:", payload)
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        data = response.json()
        print("Token response:", data)
        return data.get('access_token')
    except requests.RequestException as e:
        print("Error fetching access token:", str(e))
        print("Response status:", response.status_code)
        print("Response text:", response.text)
        return None

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

@app.route("/tiktok/accesstoken", methods=["POST"])
def get_access_token_old():
    data = request.get_json()
    code = data.get("code")
    state = data.get("state")
    code_verifier = data.get("code_verifier")

    print("Received token request:", data)

    if not all([code, state, code_verifier]):
        print("Missing parameters:", {"code": code, "state": state, "code_verifier": code_verifier})
        return jsonify({"error": "Missing required parameters"}), 400

    stored_state = request.headers.get("X-TikTok-State", "")
    if state != stored_state:
        print("State mismatch:", {"received": state, "stored": stored_state})
        return jsonify({"error": "Invalid state parameter"}), 400

    try:
        response = requests.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key": CLIENT_KEY,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        print("Token response:", response.json())
        return jsonify(response.json())
    except requests.RequestException as e:
        error_message = e.response.text if e.response else str(e)
        print(f"Error fetching access token: {error_message}")
        return jsonify({"error": "Failed to fetch access token", "details": error_message}), 500

if __name__ == "__main__":
    app.run(debug=True, port=port)
# </DOCUMENT>