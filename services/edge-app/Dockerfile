FROM python:3.11-slim

WORKDIR /app

COPY ./services/edge-app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY ./services/edge-app/app /app/app
COPY ./tcc_evidencias.py /app/tcc_evidencias.py

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
