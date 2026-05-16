FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIR=/frontend

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY frontend/ /frontend/
COPY run_addon.py /run_addon.py

EXPOSE 8124

CMD ["python", "/run_addon.py"]
