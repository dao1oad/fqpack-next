# -*- coding: utf-8 -*-

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pika
from loguru import logger
from retry import retry

from freshquant.pubsub.base import BlockingPubSubBase


class BlockingPublisher(BlockingPubSubBase):
    _pub_lock = threading.Lock()

    def __init__(
        self,
        queueName="",
        routingKey="",
        exchange="",
        exchangeType="",
        vhost="/",
        durable=False,
        auto_delete=True,
        exclusive=False,
        expiration=None,
    ):
        super().__init__(queueName, routingKey, exchange, exchangeType, vhost)
        self.durable = durable
        self.auto_delete = auto_delete
        self.exclusive = exclusive
        self.expiration = expiration
        self.prepare()

    def prepare(self):
        self.channel.exchange_declare(
            exchange=self.exchangeName,
            exchange_type=self.exchangeType,
            durable=self.durable,
            auto_delete=False,
        )
        self.channel.queue_declare(
            queue=self.queueName,
            durable=self.durable,
            auto_delete=self.auto_delete,
            exclusive=self.exclusive,
        )
        if self.exchangeType == "fanout":
            self.channel.queue_bind(queue=self.queueName, exchange=self.exchangeName)
        self.channel.confirm_delivery()

    @retry(pika.exceptions.AMQPConnectionError, delay=5, jitter=(1, 3))
    def pub(self, text):
        with self._pub_lock:
            if self.connection is None or self.connection.is_closed:
                self.re_connect()
                self.prepare()
            if isinstance(text, bytes):
                content_type = "text/plain"
            elif isinstance(text, str):
                content_type = "text/plain"
            elif isinstance(text, dict):
                content_type = "application/json"
            try:
                self.channel.basic_publish(
                    exchange=self.exchangeName,
                    routing_key=self.routingKey,
                    body=text,
                    properties=pika.BasicProperties(
                        content_type=content_type, expiration=self.expiration
                    ),
                )
            except Exception as e:
                logger.exception(e)
                raise


class BlockingPublisherRouting(BlockingPublisher):
    def __init__(
        self,
        queueName="",
        routingKey="",
        exchange="freshquant",
        vhost="/",
        durable=False,
        auto_delete=True,
        exclusive=False,
    ):
        super().__init__(
            queueName,
            routingKey,
            exchange,
            "direct",
            vhost,
            durable=durable,
            auto_delete=auto_delete,
            exclusive=exclusive,
        )


class BlockingPublisherTopic(BlockingPublisher):
    def __init__(
        self,
        queueName="",
        routingKey="",
        exchange="freshquant",
        vhost="/",
        durable=False,
        auto_delete=True,
        exclusive=False,
    ):
        super().__init__(
            queueName,
            routingKey,
            exchange,
            "topic",
            vhost,
            durable=durable,
            auto_delete=auto_delete,
            exclusive=exclusive,
        )


def test():
    threadId = threading.currentThread().ident
    pub = BlockingPublisher(
        exchange="test",
        exchangeType="fanout",
        queueName="test",
        durable=True,
        expiration=str(int(timedelta(days=1).total_seconds()) * (10**6)),
    )
    count = 0
    for i in range(60):
        pub.pub("this is a test message")
        count = count + 1
        print(threadId, count)
        time.sleep(60)


if __name__ == "__main__":
    tasks = []
    with ThreadPoolExecutor(max_workers=15) as t:
        for i in range(100):
            tasks.append(t.submit(test))
    [f.result() for f in tasks]
    print("done")
