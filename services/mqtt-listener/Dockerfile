FROM python:3.11-slim

WORKDIR /app

COPY ./services/mqtt-listener/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ./services/mqtt-listener/app /app/app

CMD ["python", "-u", "app/main.py"]