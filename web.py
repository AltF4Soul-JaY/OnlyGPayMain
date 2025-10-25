import threading
from flask import Flask, jsonify, request
import os
import asyncio
from flask_cors import CORS

# Import the new worker we just made
import cogs.web_worker 

app = Flask(__name__)

# Global variables to hold the loop and worker module
bot_loop = None
worker_module = None

# Get allowed origins from env for security
allowed_origin = os.environ.get("VERCEL_URL", "https://onlygpay.ideahatch.xyz")
CORS(app, resources={
    r"/send-message": {
        "origins": [allowed_origin, "http://localhost:3000"]
    }
})

def setup(loop, worker):
    """Receives the event loop and worker module from main.py"""
    global bot_loop, worker_module
    bot_loop = loop
    worker_module = worker
    print("Web server has received the event loop and web worker.")

@app.route('/')
def index():
    return jsonify(status="online")

@app.route('/health')
def health():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    # This logic is simple, so it can stay here
    token = request.headers.get("X-Internal-Token")
    if token != os.getenv("WEBHOOK_SECRET"):
        return "Forbidden", 403
    data = request.json
    return {"received": True}

# --- THIS ROUTE IS NOW JUST A ROUTER ---
@app.route('/send-message', methods=['POST'])
def send_message_route():
    data = request.json
    
    if not bot_loop or not worker_module:
        return jsonify({"error": "Server is not ready"}), 503

    # We are in a sync Flask thread, so we must safely call the
    # async worker function (handle_admin_message) on the bot's event loop.
    future = asyncio.run_coroutine_threadsafe(
        worker_module.handle_admin_message(data),
        bot_loop
    )
    
    # We wait for the async function to finish and get its result
    try:
        # .result() blocks this Flask thread until the worker is done
        result_dict, status_code = future.result()
        return jsonify(result_dict), status_code
    except Exception as e:
        print(f"Error in web_worker future: {e}")
        return jsonify({"error": "Failed to process request"}), 500

def start_thread():
    port = int(os.environ.get("WEB_PORT", 8080))
    threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port), daemon=True).start()
    print("Flask web server thread started.")