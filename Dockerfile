FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install web server
RUN pip install uvicorn

COPY wn/ wn/
COPY pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir ".[web]"

# Download the wordnet data and initialize the database
# CILI is for the Collaborative Interlingual Index
# ODENET is for the German WordNet (linked to CILI)
# TODO: this should be done in a separate volume
RUN python -m wn download omw:1.4 cili odenet:1.4

# Clean up the downloads directory
RUN rm -r ~/.wn_data/downloads

# Expose the port
ENV PORT=8080
EXPOSE 8080

CMD uvicorn wn.web:app --host 0.0.0.0 --port $PORT
