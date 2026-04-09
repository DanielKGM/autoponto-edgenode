Ordem de implementação

1. Infra local

Mosquitto
Redis
Docker Compose
rede entre containers

2. API local

POST /frames
GET /context/{device_id}

3. MQTT listener

ler sts/+
salvar no Redis:
estado
timestamp

4. Mock de reconhecimento

sem IA ainda
só consome fila e responde MQTT de teste

5. Reconhecimento real

OpenCV + ONNX Runtime
embeddings e matching

6. Sincronização com nuvem

pull de embeddings
push de presenças