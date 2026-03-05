# -*- coding: utf-8 -*-

import pydash

from ..config import settings

rabbitmqHost = pydash.get(settings, "rabbitmq.host", "localhost")
rabbitmqPort = pydash.get(settings, "rabbitmq.port", 5672)
rabbitmqUser = pydash.get(settings, "rabbitmq.user", "admin")
rabbitmqPassword = pydash.get(settings, "rabbitmq.password", "admin")
