import asyncio
import websockets
import json
import time
import ssl  # Import SSL for bypassing certificate verification (TEMPORARY)

# Correct WebSocket URL
WEBSOCKET_URL = "wss://flask-socketio-app-137177014687.us-central1.run.app/ws/client123?version=v1.1"

# Create SSL context to bypass SSL verification (for testing only)
ssl_context = ssl._create_unverified_context()  # TEMPORARY SSL BYPASS


async def websocket_client():
    # Store the last query sent in case reconnection is needed
    last_query = None
    last_message_id = None

    while True:  # Infinite loop for reconnection
        try:
            # Debug connection attempt
            print(f"🌐 Connecting to {WEBSOCKET_URL}")

            # Connect to the WebSocket server with SSL bypass
            async with websockets.connect(
                WEBSOCKET_URL, ping_interval=30, ping_timeout=600, ssl=ssl_context
            ) as websocket:
                print("✅ Connected to the server!")

                # If there's a pending query, resend it
                if last_query and last_message_id:
                    print(f"🔄 Resending query (ID: {last_message_id}) after reconnection...")
                    await websocket.send(json.dumps(last_query))

                    # Wait for the response to the re-sent query
                    while True:
                        response = await websocket.recv()
                        data = json.loads(response)

                        # Ignore keep-alive pings
                        if 'ping' in data:
                            continue

                        # Log server response
                        print(f"📩 Server response: {data}")

                        # Break if the final response is received for the last query
                        if data.get("message_id") == last_message_id and data.get("output") != "Processing...":
                            last_query = None  # Clear last query after receiving response
                            last_message_id = None
                            break

                # Start the normal query loop
                while True:
                    # Take user input
                    ask_user = input("\n💬 ENTER QUERY (type 'exit' to quit): ")
                    if ask_user.lower() == 'exit':
                        print("👋 Exiting chat. Goodbye!")
                        return

                    # Prepare query with unique message ID
                    last_message_id = f"msg_{int(time.time())}"
                    last_query = {
                        "message_id": last_message_id,
                        "input": ask_user
                    }

                    # Send the query to the server
                    await websocket.send(json.dumps(last_query))
                    print(f"📤 Sent query (ID: {last_message_id}):", last_query)

                    # Wait for response to the current query
                    while True:
                        response = await websocket.recv()
                        data = json.loads(response)

                        # Skip keep-alive pings
                        if 'ping' in data:
                            continue

                        # Log server response
                        print(f"📩 Server response: {data}")

                        # Exit only when final response matches the query ID
                        if data.get("message_id") == last_message_id and data.get("output") != "Processing...":
                            last_query = None  # Clear saved query after response
                            last_message_id = None
                            break

        except websockets.exceptions.ConnectionClosedError as e:
            print(f"❌ Connection closed by server: {e}")
        except websockets.exceptions.InvalidURI as e:
            print(f"❌ Invalid WebSocket URL: {str(e)}")
        except websockets.exceptions.InvalidHandshake as e:
            print(f"❌ Handshake failed: {str(e)}")
        except websockets.exceptions.ConnectionClosed as e:
            print(f"❌ Connection closed unexpectedly: {str(e)}")
        except Exception as e:
            print(f"❌ Error: {str(e)}")

        # Attempt to reconnect after 5 seconds
        print("🔄 Attempting to reconnect in 5 seconds...")
        await asyncio.sleep(5)  # Wait before reconnecting


# Start the WebSocket client
asyncio.run(websocket_client())
