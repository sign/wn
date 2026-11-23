FROM python:3.15.2-slim-trixie

WORKDIR /app
COPY requirements.lock /opt/requirements.lock

COPY wn/ wn/
COPY pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir -r /opt/requirements.lock && pip install --no-deps ".[web]"

# Download the wordnet data and initialize the database
# CILI is for the Collaborative Interlingual Index
# ODENET is for the German WordNet (linked to CILI)
RUN python -m wn download omw:1.4 cili odenet:1.4

# Load data extensions and merge them into their base lexicons so the
# Open Multilingual Wordnet ends up with one lexicon per language.
COPY extensions/wikidata-lexemes/output ./extensions/wikidata-lexemes/output
COPY extensions/wikidata-lexemes/merge_extension.py ./extensions/wikidata-lexemes/merge_extension.py
RUN python extensions/wikidata-lexemes/merge_extension.py extensions/wikidata-lexemes/output/*.xml

# Small dictionary additions maintained separately from generated Wikidata data.
COPY extensions/extras/ ./extensions/extras/
RUN python extensions/wikidata-lexemes/merge_extension.py extensions/extras/*.xml

# Curated, sense-specific examples for the most frequent English dictionary words.
COPY extensions/english-examples ./extensions/english-examples
RUN python extensions/english-examples/enrich.py

# Install the reviewed learner extension by default; minimal builds can opt out.
ARG INSTALL_ENGLISH_LEARNER=true
COPY extensions/english-learner/ ./extensions/english-learner/
RUN python extensions/english-learner/check_release.py && \
    case "$INSTALL_ENGLISH_LEARNER" in \
      true) python -c "import wn; wn.add('extensions/english-learner/rylo-en-learner.xml.gz', progress_handler=None)" ;; \
      false) echo "Learner content not installed" ;; \
      *) echo "INSTALL_ENGLISH_LEARNER must be true or false" >&2; exit 1 ;; \
    esac

# Run ANALYZE so SQLite has query planner statistics baked into the image
RUN python -c "from wn._db import connect; c = connect(); c.execute('ANALYZE')"

# Clean up the downloads directory
RUN rm -r ~/.wn_data/downloads

RUN useradd --create-home --uid 1000 app && mv /root/.wn_data /opt/wn-data && chown -R app:app /opt/wn-data
ENV WN_DATA_DIR=/opt/wn-data
USER app

# Expose the port
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn wn.web:app --host 0.0.0.0 --port $PORT"]
