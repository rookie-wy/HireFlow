"""指标注册表不变量测试（O6）。

重点：直方图必须满足 Prometheus 语义——bucket 累积单调不减、+Inf == _count。
这块逻辑在 Go/Python 两侧各错过一次（存累积值又渲染时累积 → 非单调输出），所以用测试钉死。
"""
from __future__ import annotations

import re

from app.core.metrics import inc, observe, render_prometheus, set_gauge


def _histograms(text: str) -> dict[tuple[str, str], list[tuple[float, float]]]:
    """解析直方图 bucket，按 (指标名, 标签键) 分组（不能把不同 stage 混在一起）。"""
    grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for line in text.splitlines():
        m = re.match(r'^([a-zA-Z_:][\w:]*)_bucket\{(.*?)\} (\d+)$', line)
        if not m:
            continue
        name, labels, val = m.groups()
        le = labels.split('le=')[1]
        key = (name, ",".join(sorted(p for p in labels.split(",") if not p.startswith("le="))))
        edge = float("inf") if le == "+Inf" else float(le)
        grouped.setdefault(key, []).append((edge, float(val)))
    return grouped


def test_histogram_buckets_are_cumulative_and_monotonic():
    for v in (0.3, 5.0, 0.02, 70.0):
        observe("unit_hist_seconds", v, stage="x")
    text = render_prometheus()
    groups = _histograms(text)
    key = ("unit_hist_seconds", 'stage="x"')
    assert key in groups, f"未找到直方图分组: {list(groups)}"

    points = sorted(groups[key])
    values = [v for _, v in points]
    assert values == sorted(values), f"bucket 必须累积单调不减，实际 {values}"

    count_line = [l for l in text.splitlines() if l.startswith("unit_hist_seconds_count")]
    assert count_line, "缺少 _count"
    total = float(count_line[0].split()[-1])
    assert points[-1][1] == total, f"+Inf 桶({points[-1][1]}) 必须等于 _count({total})"
    assert total == 4, f"应记录 4 次观测，实际 {total}"


def test_label_values_are_quoted():
    """标签值必须带引号（Prometheus 文本格式要求）；le 不能出现双引号套嵌。"""
    observe("unit_quote_seconds", 0.1, stage="extract")
    text = render_prometheus()
    assert 'le="' not in text, "le 不应带引号（_fmt 统一加引号）"
    assert 'stage="extract"' in text
    assert "\\\\" not in text, "不应出现转义引号"


def test_counter_no_double_total_suffix():
    inc("unit_already_total", 3)
    text = render_prometheus()
    assert "_total_total" not in text, "已带 _total 的计数器不应重复追加后缀"
    assert "unit_already_total 3" in text


def test_gauge_rendering():
    set_gauge("unit_gauge_value", 7.5, kind="db")
    text = render_prometheus()
    assert 'unit_gauge_value{kind="db"} 7.5' in text
