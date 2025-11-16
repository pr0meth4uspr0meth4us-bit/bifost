# --- Base Image ---
# Use the same slim Python 3.11 image for consistency
FROM python:3.11-slim

# --- Environment Setup ---
# Set timezone
ENV TZ=Asia/Phnom_Penh
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Set the working directory in the container
WORKDIR /app

# Set the Python path to include the /app directory
ENV PYTHONPATH=/app

# --- Dependency Installation ---
# Copy *only* the requirements file first to leverage Docker's build cache
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# --- Application Code ---
# Copy the rest of the application code (run.py, config.py, bifrost/ package, etc.)
COPY . .

# --- Runtime ---
# Expose the port the app will run on (default for Flask is 5000)
EXPOSE 5000

# Run the app using Gunicorn for production
# -w 4: Use 4 worker processes
# -b 0.0.0.0:5000: Bind to all network interfaces on port 5000
# run:app: Look in the 'run.py' file for the 'app' variable
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "run:app"]