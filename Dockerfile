FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# The headless browser rung is optional. Build with --build-arg WITH_BROWSER=1 to add it.
ARG WITH_BROWSER=0
RUN pip install --no-cache-dir . \
 && if [ "$WITH_BROWSER" = "1" ]; then \
      pip install --no-cache-dir ".[browser]" && python -m playwright install --with-deps chromium; \
    fi

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8080
CMD ["uvicorn", "scrape_ladder.api:app", "--host", "0.0.0.0", "--port", "8080"]
