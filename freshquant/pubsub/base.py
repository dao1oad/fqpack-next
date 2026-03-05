# -*- coding: utf-8 -*-

import base64
import threading

import pika

from freshquant.pubsub.setting import (
    rabbitmqHost,
    rabbitmqPassword,
    rabbitmqPort,
    rabbitmqUser,
)


class BlockingPubSubBase:

    blocking_connections = threading.local()
    blocking_lock = threading.Lock()

    def __init__(
        self,
        queueName="",
        routingKey="",
        exchange="",
        exchangeType="fanout",
        vhost="/",
    ):
        self.queueName = queueName
        self.routingKey = routingKey
        self.exchange = exchange
        self.exchangeName = f"{exchange}.{exchangeType}"
        self.exchangeType = exchangeType
        self.vhost = vhost
        self.connection = self.open_blocking_connection(self.vhost)
        self.channel = self.connection.channel()

    def open_blocking_connection(self, vhost="/"):
        with self.blocking_lock:
            conn_name = base64.b64encode(vhost.encode('utf-8')).decode('utf-8')
            conn = getattr(self.blocking_connections, conn_name)
            if conn is None or conn.is_closed:
                credentials = pika.PlainCredentials(
                    rabbitmqUser, rabbitmqPassword, erase_on_connect=True
                )
                params = pika.ConnectionParameters(
                    host=rabbitmqHost,
                    port=rabbitmqPort,
                    virtual_host=vhost,
                    credentials=credentials,
                    heartbeat=0,
                    retry_delay=10,
                    socket_timeout=10,
                    connection_attempts=10,
                )
                conn = pika.BlockingConnection(params)
                setattr(self.blocking_connections, conn_name, conn)
            return conn

    def close_blocking_connection(self, vhost="/"):
        with self.blocking_lock:
            conn_name = base64.b64encode(vhost.encode('utf-8')).decode('utf-8')
            if hasattr(self.blocking_connections, conn_name):
                conn = getattr(self.blocking_connections, conn_name)
                delattr(self.blocking_connections, conn_name)
                if conn is not None:
                    try:
                        conn.close()
                    except:
                        pass

    def re_connect(self):
        self.close_blocking_connection(self.vhost)
        self.connection = self.open_blocking_connection(self.vhost)
        self.channel = self.connection.channel()
