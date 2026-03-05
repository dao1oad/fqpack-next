# -*- coding: utf-8 -*-

from loguru import logger


def log_exception(content):
    logger.error(content)
