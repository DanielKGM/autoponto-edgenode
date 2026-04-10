#!/usr/bin/env bash
set -e

set -a
source ./.env
set +a

MQTT_PASS_DEVICE="${MQTT_PASS_DEVICE:-replace}"
MQTT_PASS_SERVICE="${MQTT_PASS_SERVICE:-replace}"

rm -f ./infra/mosquitto/passwd

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/infra/mosquitto:/mosquitto/config" \
  eclipse-mosquitto:2 \
  sh -c "
    mosquitto_passwd -b -c /mosquitto/config/passwd \"device\" \"$MQTT_PASS_DEVICE\" &&
    mosquitto_passwd -b /mosquitto/config/passwd \"service\" \"$MQTT_PASS_SERVICE\"
  "

chmod 644 ./infra/mosquitto/passwd