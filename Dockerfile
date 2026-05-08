FROM python:3.10-slim

WORKDIR /app

# Install dependencies first (cached layer — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only application code (data/ and other heavy dirs excluded via .dockerignore)
COPY . .

# Data directory is mounted as volume at runtime — create empty placeholders
RUN mkdir -p data/aiml data/dsa data/devops data/data_engineering data/design \
    data/prompt_engineering data/cloud data/fullstack data/sql

EXPOSE 7003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7003"]
