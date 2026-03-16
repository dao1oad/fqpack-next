import json
import logging
import os

from freshquant.message import dingtalk


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"errcode": 0, "errmsg": "ok"}
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload


def test_send_dingtalk_message_clears_proxy_env_during_request(monkeypatch):
    original_values = {
        "ALL_PROXY": "socks5://127.0.0.1:10808",
        "all_proxy": "socks5://127.0.0.1:10808",
        "HTTP_PROXY": "http://127.0.0.1:10809",
        "HTTPS_PROXY": "http://127.0.0.1:10809",
    }
    for key, value in original_values.items():
        monkeypatch.setenv(key, value)

    seen_during_call = {}

    def fake_post(url, data=None, headers=None):
        for key in original_values:
            seen_during_call[key] = os.environ.get(key)
        return _FakeResponse()

    monkeypatch.setattr(dingtalk.requests, "post", fake_post)

    dingtalk.send_dingtalk_message("https://example.com/robot/send", "title", "text")

    assert seen_during_call == {key: None for key in original_values}
    for key, value in original_values.items():
        assert os.environ.get(key) == value


def test_send_dingtalk_message_logs_nonzero_errcode(monkeypatch, caplog):
    def fake_post(url, data=None, headers=None):
        return _FakeResponse(payload={"errcode": 310000, "errmsg": "关键词不匹配"})

    monkeypatch.setattr(dingtalk.requests, "post", fake_post)
    caplog.set_level(logging.ERROR)

    dingtalk.send_dingtalk_message("https://example.com/robot/send", "title", "text")

    assert "310000" in caplog.text
    assert "关键词不匹配" in caplog.text
