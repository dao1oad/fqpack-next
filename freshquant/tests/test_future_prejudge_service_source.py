import re
from pathlib import Path


def test_get_future_prejudge_list_no_longer_uses_cursor_count():
    source = Path("freshquant/signal/BusinessService.py").read_text(encoding="utf-8")
    match = re.search(
        r"def getFuturePrejudgeList\(self, endDate\):(?P<body>[\s\S]*?)\n\s*#\s+更新预判信息",
        source,
    )

    assert match, "expected to find BusinessService.getFuturePrejudgeList"

    body = match.group("body")
    assert ".count()" not in body
    assert "find_one" in body or "list(" in body
