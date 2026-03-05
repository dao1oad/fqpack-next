# coding: utf-8

import ulid
from loguru import logger
from paho.mqtt import client as mqtt
from pydash import get

from freshquant.config import settings


def connect_mqtt(on_connect_callback=None, on_message_callback=None):
    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info("Connected to MQTT Broker!")
            if on_connect_callback:
                on_connect_callback(client, userdata, flags, reason_code, properties)
        else:
            logger.error(
                "Failed to connect, return code {reason_code}\n",
                reason_code=reason_code,
            )

    host = get(settings, 'emqx.host', '127.0.0.1')
    port = get(settings, 'emqx.port', 1883)
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, ulid.new().str)
    mqttc.on_connect = on_connect
    if on_message_callback:
        mqttc.on_message = on_message_callback
    mqttc.connect(host, port)
    return mqttc


if __name__ == '__main__':
    mqttc = connect_mqtt()
    mqttc.publish("test", "Hello World! from Python")
    mqttc.loop_forever()
