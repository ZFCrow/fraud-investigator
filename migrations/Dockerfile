# Runs the Alembic migrations (`alembic upgrade head`) and exits.
#
# Its own small image so that neither the server nor the ingestor has to carry the
# other's code: the migrations need the table models of both (alembic/env.py imports
# them), and nothing else needs both.
FROM python:3.11-slim
WORKDIR /app

COPY ./migrations/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# the table models env.py imports
COPY ./shared /app/shared
COPY ./server /app/server
COPY ./ingestor /app/ingestor

COPY ./migrations/alembic /app/alembic
COPY ./migrations/alembic.ini /app/alembic.ini

ENV PYTHONPATH=/app
CMD ["alembic", "upgrade", "head"]
