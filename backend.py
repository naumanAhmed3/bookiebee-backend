from flask import Flask
from flask_socketio import SocketIO, emit
from flask_cors import CORS  # Import CORS to handle cross-origin requests
from main import *  # Assuming 'executor' and 'load_vector_store' are already set up in your code

app = Flask(__name__)
# Enable CORS if frontend is on a different origin
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=30, ping_interval=20)
  # Allow any origin (or specify specific origins)

# WebSocket event to handle incoming messages from the client
@socketio.on('message')
def handle_message(message):
    try:
        # Call your agent's logic to process the received message
        load_vector_store()
        response = executor.invoke({'input': message})  
        # Send the processed response back to the client
        emit('response', response['output'])
    except Exception as e:
        # In case of error, send back a failure message
        emit('response', f"Error processing the message: {str(e)}")

def main():
    """Main function to run the Flask-SocketIO server."""
    # Run the app with the SocketIO server
    socketio.run(app, host="0.0.0.0", port=5000)  # You can change the host/port as needed

if __name__ == "__main__":
    # Ensure the main function runs when the script is executed directly
    main()
