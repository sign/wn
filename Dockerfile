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

# Load data extensions
COPY extensions/wikidata-lexemes/output ./extensions/wikidata-lexemes/output
RUN python -c "import wn; import sys; [wn.add(f) for f in sys.argv[1:]]" extensions/wikidata-lexemes/output/*.xml

# Run ANALYZE so SQLite has query planner statistics baked into the image
RUN python -c "from wn._db import connect; c = connect(); c.execute('ANALYZE')"

# Clean up the downloads directory
RUN rm -r ~/.wn_data/downloads

# Expose the port
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn wn.web:app --host 0.0.0.0 --port $PORT"]
