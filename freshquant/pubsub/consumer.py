# -*- coding: utf-8 -*-

from loguru import logger

from freshquant.pubsub.base import BlockingPubSubBase


class BlockingSubscriber(BlockingPubSubBase):
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
    ):
        super().__init__(queueName, routingKey, exchange, exchangeType, vhost)
        self.durable = durable
        self.auto_delete = auto_delete
        self.exclusive = exclusive
        self.prepare()

    def onMessage(self, chan, method, properties, body, userdata=None):
        logger.info(
            {"chan": chan, "method": method, "properties": properties, "body": body}
        )

    def subscribe(self):
        self.channel.basic_consume(self.queueName, self.onMessage, auto_ack=True)
        self.channel.start_consuming()

    def prepare(self):
        self.channel.exchange_declare(
            exchange=self.exchange,
            exchange_type=self.exchangeType,
            durable=self.durable,
            auto_delete=False,
        )
        self.queue = self.channel.queue_declare(
            queue=self.queueName,
            auto_delete=self.auto_delete,
            exclusive=self.exclusive,
            durable=self.durable,
        ).method.queue
        self.channel.queue_bind(
            queue=self.queue, exchange=self.exchange, routing_key=self.routingKey
        )

    def start(self):
        try:
            self.subscribe()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.exception(e)
            self.re_connect()
            self.prepare()
            self.start()


class BlockingSubscriberRouting(BlockingSubscriber):
    def __init__(
        self,
        channelNumber=1,
        queueName="",
        routingKey="defalut",
        exchange="freshquant",
        vhost="/",
        durable=False,
    ):
        super().__init__(
            channelNumber,
            queueName,
            routingKey,
            exchange,
            "direct",
            vhost,
            durable=durable,
        )


class BlockingSubscriberRouting(BlockingSubscriber):
    def __init__(
        self,
        channelNumber=1,
        queueName="",
        routingKey="defalut",
        exchange="freshquant",
        vhost="/",
        durable=False,
    ):
        super().__init__(
            channelNumber,
            queueName,
            routingKey,
            exchange,
            "topic",
            vhost,
            durable=durable,
        )
