# -*- coding: utf-8 -*-

import json
import urllib.parse

from freshquant.config import settings


def get_api_base_url() -> str:
    """获取 API 基础地址，支持环境变量覆盖

    优先级：环境变量 > 配置文件 > 默认值
    环境变量格式: freshquant_API__BASE_URL

    Returns:
        API 基础地址，默认为 http://host.docker.internal

    Examples:
        >>> # 默认值
        >>> get_api_base_url()
        'http://host.docker.internal'

        >>> # 通过环境变量覆盖
        >>> # export freshquant_API__BASE_URL="http://192.168.1.100:8080"
        >>> get_api_base_url()
        'http://192.168.1.100:8080'
    """
    return settings.get('api', {}).get('base_url', 'http://host.docker.internal')


def fq_util_url_join(url, *paths):
    for path in paths:
        url = url.rstrip('/') + '/' + path.lstrip('/')
    return url


def fq_util_url_encode(params, doseq=False):
    if params and isinstance(params, dict):
        for key, value in params.items():
            if isinstance(value, bool):
                params[key] = 'true' if value else 'false'
        return urllib.parse.urlencode(params, doseq)
    return ''


def fq_util_parse_query_params(query_params):
    """
    解析查询参数
    :param query_params: 查询参数
    :return: 查询参数字典
    """
    query = query_params.pop('query', '{}')
    page = int(query_params.pop('page', 1))
    size = int(query_params.pop('size', 10))
    sort = query_params.pop('sort', '{"_id": -1}')
    sort = [(key, value) for key, value in json.loads(sort).items()]
    project = query_params.pop('project', None)
    project = json.loads(project) if project else None
    return json.loads(query), page, size, sort, project
