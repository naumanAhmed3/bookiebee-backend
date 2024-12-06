import socketio

# Create a Socket.IO client
sio = socketio.Client()

# Connect to the Flask-SocketIO server (replace with the correct IP/hostname if necessary)
server_url = 'http://localhost:5000'  # Use Flask server URL here, not Redis
sio.connect(server_url)

# Event handler when connected to the server
@sio.event
def connect():
    print("Connected to the server!")

# Event handler for the response from the server
@sio.event
def response(data):
    print("Received response from server:", data)

# Event handler when disconnected from the server
@sio.event
def disconnect():
    print("Disconnected from the server.")

# Send a message to the server
def send_message(message):
    print("Sending message:", message)
    sio.emit('message', message)

# Wait for user input to send messages
if __name__ == "__main__":
    try:
        while True:
            message = input("Enter message to send to the server: ")
            if message.lower() == 'exit':
                break
            send_message(message)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        sio.disconnect()
