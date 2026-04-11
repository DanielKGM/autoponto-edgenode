FROM python:3.11-slim

WORKDIR /app

COPY ./services/face-worker/requirements.txt /app/requirements.txt
RUN  pip install --no-cache-dir -r /app/requirements.txt

COPY ./services/face-worker/app /app/app

CMD ["python", "-u", "app/main.py"]
