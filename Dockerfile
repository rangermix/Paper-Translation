# This image hosts the delivered prototype/docs, not a production PDF translation backend.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /site
COPY . /site
USER 10001:10001
EXPOSE 8080
CMD ["python", "tools/serve_prototype.py", "--host", "0.0.0.0", "--port", "8080"]
