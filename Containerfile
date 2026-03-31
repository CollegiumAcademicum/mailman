# Use an official Python runtime as a parent image
FROM python:3.12.13-slim

# Set the working directory in the container
WORKDIR /app

# Install uv, a fast Python package installer
RUN pip install uv

# Copy the dependency definitions
COPY pyproject.toml .

# Install dependencies using uv
RUN uv sync

# Copy the rest of the application code
COPY . .

# Command to run tests (for testing purposes)
# CMD ["uv", "run", "pytest"]

# Command to run the application
CMD ["uv", "run", "python", "main.py"]
