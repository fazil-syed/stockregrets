FROM python:3.12-slim

WORKDIR /app

RUN pip install poetry

COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root --no-interaction

RUN poetry run playwright install chromium

COPY . .

CMD [ "poetry", "run", "python", "-m", "app.main" ]