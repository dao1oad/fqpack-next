"""证据包加载与按报告期缓存。

静态财务证据按 (symbol, 报告期) 缓存复用；行情证据按交易日刷新。证据的
来源、抓取时间、报告期与哈希随每条记录保存，保证可追溯。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
from typing import Any, Iterable


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def normalize_symbol(value: Any) -> str:
    text = clean_text(value).lower()
    if text.startswith(("sh", "sz", "bj")):
        text = text[2:]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def pick_industry(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """按机构偏好与变更日期选择最新行业归属（与既有 CLX 评价链路同口径）。"""
    preferences = (
        "申银万国行业分类标准",
        "中证行业分类标准",
        "巨潮行业分类标准",
        "中国上市公司协会上市公司行业分类标准",
        "证监会行业分类标准",
    )
    candidates = [
        row
        for row in rows
        if any(
            preference in clean_text(row.get("分类标准")) for preference in preferences
        )
    ]
    candidates.sort(key=lambda row: clean_text(row.get("变更日期")), reverse=True)
    for row in candidates:
        for field in ("行业中类", "行业大类", "行业次类", "行业门类"):
            industry = clean_text(row.get(field))
            if industry:
                return {
                    "industry": industry,
                    "standard": clean_text(row.get("分类标准")),
                    "effective_date": clean_text(row.get("变更日期"))[:10],
                    "institution": clean_text(row.get("机构名称")),
                }
    raise ValueError("CNINFO industry cascade produced no industry")


def business_fields(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    row = next(iter(rows), {})
    return {
        "main_business": clean_text(row.get("主营业务")),
        "product_types": clean_text(row.get("产品类型")),
        "product_names": clean_text(row.get("产品名称")),
        "business_scope": clean_text(row.get("经营范围")),
    }


def broad_group(industry: str, business: str) -> str:
    """业务 primary_group（统计的行业维度），与既有评价链路同口径。"""
    rules = (
        (
            "医药生物与医疗",
            ("化学制剂", "原料药", "生物制品", "医疗", "诊断", "药", "疫苗"),
        ),
        (
            "电子与半导体",
            ("半导体", "芯片", "电子", "印制电路", "光学元件", "消费电子", "磁性材料"),
        ),
        (
            "计算机通信与传媒",
            (
                "计算机",
                "软件",
                "IT服务",
                "安防",
                "通信",
                "游戏",
                "传媒",
                "营销代理",
                "网络设备",
            ),
        ),
        (
            "电力设备与新能源",
            (
                "电源设备",
                "配电",
                "电网",
                "电机",
                "线缆",
                "风电零部件",
                "光伏加工",
                "锂电池",
                "电池化学品",
                "电气设备",
            ),
        ),
        (
            "公用事业与能源",
            (
                "风力发电",
                "光伏发电",
                "热力",
                "燃气",
                "电能综合",
                "电力",
                "油品石化",
                "能源供应",
            ),
        ),
        (
            "国防军工与机械",
            (
                "通用设备",
                "专用设备",
                "重型设备",
                "机器人",
                "轨交",
                "航天",
                "航空",
                "航海",
                "军工",
                "激光设备",
                "机械",
                "楼宇设备",
            ),
        ),
        ("基础化工", ("氯碱", "涂料", "油墨", "塑料", "化学纤维", "化学制品", "化工")),
        (
            "资源材料与建材",
            (
                "金属",
                "水泥",
                "铜",
                "小金属",
                "钨",
                "铅锌",
                "防水材料",
                "建材",
                "钢铁",
                "材料",
            ),
        ),
        (
            "汽车与交通运输",
            ("汽车零部件", "底盘", "发动机", "整车", "交通运输", "物流"),
        ),
        (
            "食品农业与消费",
            (
                "乳品",
                "果蔬",
                "食品",
                "饲料",
                "小家电",
                "家电",
                "家纺",
                "纺织",
                "文化用品",
                "娱乐用品",
                "家居",
                "彩电",
                "卫浴",
            ),
        ),
        (
            "建筑环保与工程",
            ("固废", "环保", "装修", "工程咨询", "基建", "专业工程", "建筑", "市政"),
        ),
        (
            "商贸零售与社会服务",
            ("景区", "培训", "教育", "超市", "旅游", "零售", "社会服务"),
        ),
        ("金融与地产", ("证券", "银行", "农商行", "地产", "保险")),
    )
    for source_text in (industry, business):
        for group_name, tokens in rules:
            if any(token in source_text for token in tokens):
                return group_name
    return "综合与专业服务"


def financial_snapshot(
    rows: Iterable[dict[str, Any]], cutoff: str
) -> tuple[str, dict[str, float | None]]:
    """选择报告期 <= cutoff 的最新一期财务指标（as-of 安全）。"""
    eligible = sorted(
        {
            clean_text(row.get("report_date"))[:10]
            for row in rows
            if clean_text(row.get("report_date"))[:10] <= cutoff
            and clean_text(row.get("report_date"))[:10]
        },
        reverse=True,
    )
    if not eligible:
        raise ValueError("no as-of-safe financial report")
    report_date = eligible[0]
    selected = {
        clean_text(row.get("metric_name")): number(row.get("value"))
        for row in rows
        if clean_text(row.get("report_date"))[:10] == report_date
    }
    return report_date, selected


def evidence_grade(sources: dict[str, Any], financial: bool = True) -> str:
    """证据覆盖等级：A/B/C/D。

    - A：财务 + 行业 + 业务 + 行情四类来源齐全
    - B：财务 + 行业 + 行情（业务缺失）
    - C：财务 + 行情
    - D：仅部分来源或全部缺失
    """
    has = {
        "financial": financial and bool(sources.get("ths_financial")),
        "industry": bool(sources.get("cninfo_industry")),
        "business": bool(sources.get("ths_business")),
        "quote": bool(sources.get("sina_spot") or sources.get("quote")),
    }
    present = sum(1 for value in has.values() if value)
    if present >= 4:
        return "A"
    if present >= 3:
        return "B"
    if present >= 2:
        return "C"
    return "D"


class EvidenceCache:
    """证据缓存库。

    布局：
      <root>/stock/<symbol>.json.gz          单标的证据包（含全部来源）
      <root>/cache/<symbol>/<report>.json    按 (symbol, 报告期) 的静态财务缓存
      <root>/quotes/<trade-date>.json        当日行情快照（每日刷新）
    """

    def __init__(self, root: pathlib.Path) -> None:
        self.root = pathlib.Path(root)
        self.stock_dir = self.root / "stock"
        self.cache_dir = self.root / "cache"
        self.quote_dir = self.root / "quotes"

    def load_stock(self, symbol: str) -> dict[str, Any]:
        """读取单标的证据包；不存在时返回空结构。"""
        normalized = normalize_symbol(symbol)
        if not normalized:
            return {
                "symbol": symbol,
                "captured_at": "",
                "as_of_policy": {},
                "sources": {},
                "errors": [],
            }
        for path in (
            self.stock_dir / f"{normalized}.json.gz",
            self.stock_dir / f"{normalized}.json",
        ):
            if path.is_file():
                if path.name.endswith(".gz"):
                    with gzip.open(path, "rt", encoding="utf-8") as stream:
                        payload = json.load(stream)
                else:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                return payload
        return {
            "symbol": normalized,
            "captured_at": "",
            "as_of_policy": {},
            "sources": {},
            "errors": [],
        }

    def save_stock(self, payload: dict[str, Any]) -> pathlib.Path:
        symbol = normalize_symbol(payload.get("symbol"))
        if not symbol:
            raise ValueError("evidence payload missing symbol")
        self.stock_dir.mkdir(parents=True, exist_ok=True)
        path = self.stock_dir / f"{symbol}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        return path

    def financial_cache_key(self, symbol: str, report_date: str) -> pathlib.Path:
        return self.cache_dir / normalize_symbol(symbol) / f"{report_date}.json"

    def load_financial_cached(
        self, symbol: str, report_date: str
    ) -> dict[str, Any] | None:
        path = self.financial_cache_key(symbol, report_date)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_financial_cached(
        self,
        symbol: str,
        report_date: str,
        metrics: dict[str, float | None],
        provenance: dict[str, Any],
    ) -> pathlib.Path:
        payload = {
            "symbol": normalize_symbol(symbol),
            "report_date": report_date,
            "metrics": {
                key: value
                for key, value in sorted(metrics.items())
                if value is not None
            },
            "provenance": provenance,
            "payload_hash": sha256_bytes(
                _stable_json(
                    {
                        "report_date": report_date,
                        "metrics": {
                            key: value
                            for key, value in sorted(metrics.items())
                            if value is not None
                        },
                    }
                )
            ),
        }
        path = self.financial_cache_key(symbol, report_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return path

    def seed_financial_cache(
        self,
        symbol: str,
        report_date: str,
        metrics: dict[str, float | None],
        provenance: dict[str, Any],
    ) -> bool:
        """静态财务按 (symbol, 报告期) 幂等缓存；已存在时复用（返回 False）。"""
        if self.load_financial_cached(symbol, report_date) is not None:
            return False
        self.save_financial_cached(symbol, report_date, metrics, provenance)
        return True

    def evidence_package(
        self, symbol: str, financial_cutoff: str, trade_date: str
    ) -> dict[str, Any]:
        """从证据包提取标准字段包：行业/业务/财务/行情 + 溯源。"""
        payload = self.load_stock(symbol)
        sources = payload.get("sources", {}) or {}
        try:
            industry = pick_industry(sources.get("cninfo_industry") or [])
        except ValueError:
            industry = {}
        business = business_fields(sources.get("ths_business") or [])
        try:
            report_date, metrics = financial_snapshot(
                sources.get("ths_financial") or [], financial_cutoff
            )
        except ValueError:
            report_date, metrics = "", {}
        financial_rows = list(sources.get("ths_financial") or [])
        provenance = {
            "captured_at": clean_text(payload.get("captured_at")),
            "as_of_policy": payload.get("as_of_policy") or {},
            "financial_source_count": len(financial_rows),
            "source_sha256": sha256_bytes(_stable_json({"sources": sources})),
        }
        cached = None
        if report_date:
            cached = self.load_financial_cached(symbol, report_date)
            if cached is None:
                self.save_financial_cached(symbol, report_date, metrics, provenance)
                cached = self.load_financial_cached(symbol, report_date)
        quote = sources.get("sina_spot") or sources.get("quote") or {}
        return {
            "symbol": normalize_symbol(symbol),
            "name": clean_text(payload.get("name")) or clean_text(quote.get("name")),
            "trade_date": trade_date,
            "financial_cutoff": financial_cutoff,
            "industry": industry,
            "business": business,
            "primary_group": broad_group(
                industry.get("industry", ""), business.get("main_business", "")
            ),
            "report_date": report_date,
            "metrics": (
                (cached or {}).get("metrics", metrics)
                if cached is not None
                else metrics
            ),
            "financial_cache": {
                "cached": cached is not None,
                "cache_key": report_date,
                "payload_hash": (cached or {}).get("payload_hash", ""),
            },
            "quote": {
                "latest_price": number(
                    quote.get("最新价") if isinstance(quote, dict) else None
                ),
                "amount_yi": number(
                    quote.get("成交额(元)") if isinstance(quote, dict) else None
                ),
            },
            "evidence": {
                "grade": evidence_grade(sources),
                "ids": sorted(
                    {
                        (
                            f"CNINFO-INDUSTRY-{normalize_symbol(symbol)}"
                            if sources.get("cninfo_industry")
                            else ""
                        ),
                        (
                            f"THS-BUSINESS-{normalize_symbol(symbol)}"
                            if sources.get("ths_business")
                            else ""
                        ),
                        (
                            f"THS-FINANCIAL-{normalize_symbol(symbol)}"
                            if sources.get("ths_financial")
                            else ""
                        ),
                        (
                            f"QUOTE-{trade_date.replace('-', '')}"
                            if (sources.get("sina_spot") or sources.get("quote"))
                            else ""
                        ),
                    }
                    - {""}
                ),
                "source_sha256": provenance["source_sha256"],
                "captured_at": provenance["captured_at"],
            },
            "errors": payload.get("errors") or [],
        }
