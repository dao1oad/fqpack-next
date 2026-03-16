import json
import logging
import traceback

import requests  # type: ignore[import-untyped]
from blinker import signal
from ratelimit import limits, sleep_and_retry

from freshquant.runtime.network import without_proxy_env
from freshquant.system_settings import system_settings

order_alert = signal("order_alert")
market_data_alert = signal("market_data_alert")


@sleep_and_retry
@limits(calls=1, period=10)
def send_dingtalk_message(url, title, text):
    if url is not None and title is not None and text is not None:
        try:
            with without_proxy_env():
                response = requests.post(
                    url,
                    data=json.dumps(
                        {
                            "msgtype": "markdown",
                            "markdown": {"title": f"freshquant: {title}", "text": text},
                        }
                    ),
                    headers={"Content-Type": "application/json"},
                )
            if getattr(response, "status_code", 200) >= 400:
                logging.error(
                    "DingTalk HTTP error: status=%s body=%s",
                    getattr(response, "status_code", ""),
                    getattr(response, "text", ""),
                )
                return
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and int(payload.get("errcode") or 0) != 0:
                logging.error(
                    "DingTalk rejected message: errcode=%s errmsg=%s body=%s",
                    payload.get("errcode"),
                    payload.get("errmsg"),
                    getattr(response, "text", ""),
                )
        except Exception as e:
            logging.error("Error Occurred: {0} {1}".format(e, traceback.format_exc()))


def send_private_message(title, text, *, settings_provider=None):
    settings_provider = settings_provider or system_settings
    send_dingtalk_message(
        getattr(settings_provider.notification, "dingtalk_private_webhook", ""),
        title,
        text,
    )


def send_public_message(title, text, *, settings_provider=None):
    settings_provider = settings_provider or system_settings
    send_dingtalk_message(
        getattr(settings_provider.notification, "dingtalk_public_webhook", ""),
        title,
        text,
    )


@order_alert.connect
def send_order_alert_to_dingtalk(sender, **kwargs):
    payload = kwargs.get("payload")
    fields = {
        'position': payload.get("position", ""),
        'code': payload.get("code", ""),
        'name': payload.get("name", ""),
        'period': payload.get("period", ""),
        'price': payload.get("price", ""),
        'quantity': payload.get("quantity", ""),
        'fire_time': (
            payload.get("fire_time", "").strftime("%Y年%m月%d日%H时%M分%S秒")
            if payload.get("fire_time", "")
            else ""
        ),
        'discover_time': (
            payload.get("discover_time", "").strftime("%Y年%m月%d日%H时%M分%S秒")
            if payload.get("discover_time", "")
            else ""
        ),
        'delay': (
            int(
                (
                    payload.get("discover_time", "") - payload.get("fire_time", "")
                ).total_seconds()
            )
            if payload.get("discover_time", "") and payload.get("fire_time", "")
            else 0
        ),
        'remark': payload.get("remark", ""),
    }

    title = f'{("买点通知" if fields["position"] == "BUY_LONG" else "卖点通知")}-{fields["code"]}-{fields["name"]}'
    text_lines = [
        f'### {title}',
        f'> 周期: {fields["period"].upper()}, 方向: {"买点" if fields["position"] == "BUY_LONG" else "卖点"}, 价格: {fields["price"]}, 数量: {fields["quantity"]}',
        f'> 触发时间: {fields["fire_time"]}',
        f'> 发现时间: {fields["discover_time"]}',
        f'> 信号延迟: {fields["delay"]}秒',
        f'> 备注: {fields["remark"]}',
        f'> sender: {sender}',
    ]

    (send_private_message if kwargs.get("private", False) else send_public_message)(
        title, '  \n'.join(text_lines)
    )


@market_data_alert.connect
def send_market_data_alert_to_dingtalk(sender, **kwargs):
    payload = kwargs.get("payload")
    fields = {
        'title': payload.get('title', ''),
        'content': payload.get('content', ''),
    }

    title = fields['title']
    text_lines = [f'### {title}', f'{fields["content"]}', f'sender: {sender}']

    send_private_message(title, '  \n'.join(text_lines))
