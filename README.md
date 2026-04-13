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

mDNS autopontonode.local

```bash
sudo hostnamectl set-hostname autopontonode
sudo apt update
sudo apt install avahi-daemon
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
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

POST /frames (X)
GET /context/{device_id} (X)

3. MQTT listener

ler sts/+ (X)
salvar no Redis: (X)
estado 
timestamp

4. Mock de reconhecimento

sem IA ainda (X)
só consome fila e responde MQTT de teste (X)

5. Reconhecimento real

OpenCV + ONNX Runtime (X)
embeddings e matching (X)

Modelos ([OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main)):

```bash
wget https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx -O ./data/models/face_detection_yunet.onnx

wget https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx -O ./data/models/face_recognition_sface.onnx
```


6. Sincronização com nuvem

pull de embeddings ( )
push de presenças ( )