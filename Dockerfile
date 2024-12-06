# Use a specific version of Python runtime as the base image
FROM python:3.10-slim

# Set environment variables to avoid buffering of stdout and stderr
ENV PYTHONUNBUFFERED=1

# Create a non-root user and set appropriate permissions
RUN useradd -m appuser
USER appuser

# Set the working directory in the container
WORKDIR /app

# Copy only the requirements.txt file to leverage Docker cache layer
COPY --chown=appuser:appuser requirements.txt /app/

# Upgrade pip, install dependencies with retries, timeout, and mirror options
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --retries 10 --timeout=5000 --prefer-binary -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Copy the rest of the application code into the container
COPY --chown=appuser:appuser . /app/

# Install eventlet and gunicorn globally
RUN pip install --no-cache-dir gevent
RUN pip install --no-cache-dir eventlet
RUN pip install --no-cache-dir gunicorn

# Ensure gunicorn is available by updating the PATH if installed locally for the user
ENV PATH="/home/appuser/.local/bin:$PATH"

# Expose the port the app will run on
EXPOSE 5000

# Command to run the Flask app using Gunicorn with eventlet worker for WebSockets
CMD ["python","backend.py"]

