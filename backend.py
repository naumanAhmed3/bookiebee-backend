from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
import json
from main import *  # Import LangChain executor
from typing import Dict
import asyncio

# Allowed versions
ALLOWED_VERSIONS = ['v1.1', 'v1.0']

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session storage
sessions: Dict[str, dict] = {}


async def keep_alive(websocket):
    """Keep connection alive with periodic pings."""
    while True:
        try:
            await websocket.send_text(json.dumps({"ping": "keep-alive"}))
            await asyncio.sleep(30)  # Ping every 30 seconds
        except Exception as e:
            print("Ping failed, connection lost:", e)
            break


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, version: str = Query(...)):
    if version not in ALLOWED_VERSIONS:
        await websocket.close(code=1008)
        return

    # Session setup
    if session_id not in sessions:
        sessions[session_id] = {
            "pending": [],
            "memory": []
        }

    # Accept connection
    await websocket.accept()
    print(f"✅ Client connected: session_id={session_id}, version={version}")

    # Start keep-alive task
    asyncio.create_task(keep_alive(websocket))

    try:
        # Handle pending responses
        for response in sessions[session_id]["pending"]:
            await websocket.send_text(json.dumps(response))
        sessions[session_id]["pending"] = []

        while True:
            # Receive message
            data = await websocket.receive_text()
            data = json.loads(data)

            if 'input' not in data:
                await websocket.send_text(json.dumps({'output': 'Invalid input format.'}))
                continue

            user_input = data['input']

            # Acknowledge
            await websocket.send_text(json.dumps({
                'message_id': data.get('message_id', 'unknown'),
                'output': 'Processing...'
            }))

            try:
                # Process input with a 300-second timeout
                result = await asyncio.wait_for(
                    asyncio.to_thread(executor.invoke, {'input': user_input}), timeout=300
                )
                response = {
                    'message_id': data.get('message_id', 'unknown'),
                    'output': result.get('output', "Sorry, I couldn't process your query.")
                }
                await websocket.send_text(json.dumps(response))

            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({
                    'message_id': data.get('message_id', 'unknown'),
                    'output': "Server took too long to respond."
                }))
            except Exception as e:
                await websocket.send_text(json.dumps({
                    'message_id': data.get('message_id', 'unknown'),
                    'output': f"Error: {str(e)}"
                }))

    except WebSocketDisconnect:
        print(f"❌ Client disconnected: session_id={session_id}")
    except Exception as e:
        print(f"❌ Backend Error: {str(e)}")
    finally:
        # Cleanup session if required
        pass


@app.get("/")
async def health_check():
    return {"status": "OK"}
