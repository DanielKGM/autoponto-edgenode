Ordem de implementação

0. Env

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt install docker-compose-plugin -y
sudo sysctl vm.overcommit_memory=1
```

firewall

```bash
sudo apt install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 1883/tcp
sudo ufw allow 22/tcp
sudo ufw allow 8080/tcp
```

automatic start

```bash
sudo nano /etc/systemd/system/edge-node.service
# put edge-node.service content here
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable edge-node
#test sudo systemctl start edge-node \ systemctl status edge-node
```


1. Infra local

Mosquitto (X)
Redis (X)
Docker Compose (X)
rede entre containers (X)

```bash
chmod +x scripts/init-mosquitto-password.sh
```

```bash
touch .env
cp .env.example .env
```

2. API local

POST /frames ( )
GET /context/{device_id} ( )

3. MQTT listener

ler sts/+ ( )
salvar no Redis: ( )
estado 
timestamp

4. Mock de reconhecimento

sem IA ainda ( )
só consome fila e responde MQTT de teste ( )

5. Reconhecimento real

OpenCV + ONNX Runtime ( )
embeddings e matching ( )

6. Sincronização com nuvem

pull de embeddings ( )
push de presenças ( )