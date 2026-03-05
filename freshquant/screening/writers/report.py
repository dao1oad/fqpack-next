# -*- coding: utf-8 -*-
"""报表输出

生成 HTML 报表、控制台表格输出
"""

import os
from datetime import datetime

import pandas as pd
from tabulate import tabulate
from tqdm import tqdm

from freshquant.screening.base.strategy import ScreenResult


class ReportOutput:
    """报表输出处理器"""

    @staticmethod
    def print_table(results: list[ScreenResult], title: str = "选股结果"):
        """打印表格到控制台

        Args:
            results: 选股结果列表
            title: 标题
        """
        if not results:
            print("无结果")
            return

        data = []
        for r in results:
            data.append({
                "代码": r.code,
                "名称": r.name,
                "分类": r.category or "-",
                "周期": r.period,
                "时间": r.fire_time.strftime("%Y-%m-%d %H:%M"),
                "价格": r.price,
                "止损": r.stop_loss_price or "-",
                "信号": r.signal_type,
                "标签": ",".join(r.tags) if r.tags else "-",
            })

        df = pd.DataFrame(data)
        df.sort_values(["时间"], ascending=[False], inplace=True)

        print(f"\n{title}")
        print(tabulate(df, headers="keys", tablefmt="pretty", showindex=False))

    @staticmethod
    def save_html(
        results: list[ScreenResult],
        output_dir: str = "report",
        filename: str | None = None,
        title: str = "选股结果",
    ):
        """生成 HTML 报表

        Args:
            results: 选股结果列表
            output_dir: 输出目录
            filename: 文件名（默认使用 title）
            title: 报表标题
        """
        if not results:
            return

        os.makedirs(output_dir, exist_ok=True)

        data = []
        codes = []
        for r in results:
            data.append({
                "code": r.code,
                "name": r.name,
                "symbol": r.symbol,
                "category": r.category or "-",
                "period": r.period,
                "fire_time": r.fire_time.strftime("%Y-%m-%d %H:%M"),
                "price": r.price,
                "stop_loss_price": r.stop_loss_price or "-",
                "signal_type": r.signal_type,
                "tags": ",".join(r.tags) if r.tags else "-",
                "position": r.position,
            })
            codes.append(r.code)

        df = pd.DataFrame(data)
        df.sort_values(["fire_time"], ascending=[False], inplace=True)
        df.reset_index(drop=True, inplace=True)

        # 生成带样式的 HTML
        styled_df = (
            df.style
            .set_caption(title)
            .set_table_styles([
                {"selector": "caption", "props": [("text-align", "left")]},
                {"selector": "th", "props": [
                    ("background-color", "#f0f0f0"),
                    ("text-align", "left"),
                    ("padding", "2px")
                ]},
                {"selector": "td", "props": [
                    ("text-align", "left"),
                    ("padding", "2px")
                ]}
            ])
            .highlight_null(color="lightgrey")
            .set_properties(subset=["code"], **{
                "color": "darkblue",
                "font-weight": "bold"
            })
        )

        filename = filename or f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = os.path.join(output_dir, filename)

        # 生成带复制按钮的 HTML
        html = styled_df.to_html(encoding="utf-8")
        unique_codes = "\n".join(set(codes))

        # 添加复制按钮
        copy_button_html = f"""
<script type="text/javascript">
function copyCodes() {{
    const codes = `{unique_codes}`;
    navigator.clipboard.writeText(codes).then(() => {{
        alert('已复制 ' + codes.split('\\n').length + ' 个股票代码');
    }}).catch(err => {{
        alert('复制失败: ' + err);
    }});
}}
</script>
<button onclick="copyCodes()" style="padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-bottom: 10px;">
    复制股票代码到剪贴板
</button>
<br>
"""

        # 插入按钮到 HTML 开头（在 <style> 标签之后）
        html = html.replace('</style>', f'</style>{copy_button_html}')

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"报表已保存: {filepath}")

    @staticmethod
    def show_progress(results: list[ScreenResult], desc: str = "处理中"):
        """显示进度条（用于调试）

        Args:
            results: 选股结果列表
            desc: 描述
        """
        for _ in tqdm(results, desc=desc):
            pass
