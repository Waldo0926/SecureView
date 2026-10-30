FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
# Keep the lab image an explicit source allowlist. A deployed release also contains its
# runtime venv and may contain local logs or staging directories; none belongs in an attacker
# image even when .dockerignore is accidentally weakened later.
COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY tests ./tests
# Some Python distributions install an unrelated top-level `tests` package. Make the copied
# SecureView test helpers an explicit package inside this lab image so they cannot be shadowed.
RUN touch tests/__init__.py tests/integration/__init__.py

RUN groupadd --gid 10001 lab && useradd --uid 10001 --gid lab --no-create-home lab
USER 10001:10001
