"""进程内指标注册表（零依赖，Prometheus 文本格式导出）。

设计取舍：不引第三方客户端——本身只服务单实例、指标量小，
用固定桶直方图 + 计数器足够，避免为埋点引入新依赖与网络安装。

用法：
    from app.core.metrics import observe, inc, timer, render_prometheus

    with timer("parse_stage_seconds", stage="llm"):
        ...
    inc("parse_total", status="ok")
    print(render_prometheus())
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, Iterable, Tuple

# 直方图桶（秒）：覆盖 50ms ~ 60s，够看解析/LLM/向量化各阶段
_BUCKETS: Tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34, 60)

_lock = threading.Lock()
_counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_hist_sum: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_hist_count: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], int] = defaultdict(int)
_hist_buckets: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], list] = {}
# 超出最大桶边界的观测数（归入 +Inf）
counts_overflow: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], int] = {}
_gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}


def _key(name: str, labels: Dict[str, str] | None) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    return name, tuple(sorted((labels or {}).items()))


def _fmt(labels: Iterable[Tuple[str, str]], extra: str = "") -> str:
    """标签串。

    注意：**所有**标签值都必须带引号（Prometheus 文本格式要求），
    `le` 也走同一规则——早先直接把 `le="0.5"` 当裸字符串拼进去，
    再补引号时产生了 `le="\"0.5\""` 这类畸形输出，导致抓取端解析失败。
    """
    items = [f'{k}="{v}"' for k, v in labels]
    if extra:
        items.append(extra)
    return "{" + ",".join(items) + "}" if items else ""


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    """计数器 +1（或 +value）。"""
    with _lock:
        _counters[_key(name, labels)] += value


def set_gauge(name: str, value: float, **labels: str) -> None:
    with _lock:
        _gauges[_key(name, labels)] = value


def observe(name: str, seconds: float, **labels: str) -> None:
    """直方图观测（秒）。"""
    k = _key(name, labels)
    with _lock:
        _hist_sum[k] += seconds
        _hist_count[k] += 1
        buckets = _hist_buckets.get(k)
        if buckets is None:
            buckets = [0] * len(_BUCKETS)
            _hist_buckets[k] = buckets
        # 只累加到**第一个**满足 seconds<=edge 的桶（区间计数），
        # 渲染时再做累积——存累积值又要渲染时累积会得到非单调输出（踩过一次）
        placed = False
        for i, edge in enumerate(_BUCKETS):
            if seconds <= edge:
                buckets[i] += 1
                placed = True
                break
        if not placed:
            counts_overflow[k] = counts_overflow.get(k, 0) + 1


@contextmanager
def timer(name: str, **labels: str):
    """with timer("x", stage="llm"): ... 自动观测耗时（异常也记录）。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - start, **labels)


def snapshot() -> dict:
    """当前指标快照（供日志/调试使用）。"""
    with _lock:
        return {
            "counters": {f"{n}{_fmt(l)}": v for (n, l), v in _counters.items()},
            "histograms": {
                f"{n}{_fmt(l)}": {
                    "count": _hist_count[(n, l)],
                    "sum": round(_hist_sum[(n, l)], 4),
                    "avg": round(_hist_sum[(n, l)] / max(_hist_count[(n, l)], 1), 4),
                }
                for (n, l) in _hist_count
            },
            "gauges": {f"{n}{_fmt(l)}": v for (n, l), v in _gauges.items()},
        }


def render_prometheus() -> str:
    """按 Prometheus 文本格式导出（含 _bucket/_sum/_count）。"""
    lines: list[str] = []
    with _lock:
        for (name, labels), value in sorted(_counters.items()):
            # 已以 _total 结尾的计数器不重复追加（Prometheus 规范）
            suffix = "" if name.endswith("_total") else "_total"
            lines.append(f"{name}{suffix}{_fmt(labels)} {value:g}")
        for (name, labels), value in sorted(_gauges.items()):
            lines.append(f"{name}{_fmt(labels)} {value:g}")
        for (name, labels), count in sorted(_hist_count.items()):
            buckets = _hist_buckets.get((name, labels)) or [0] * len(_BUCKETS)
            cumulative = 0
            for edge, hits in zip(_BUCKETS, buckets):
                cumulative += hits
                lines.append(f"{name}_bucket{_fmt(labels, f'le={edge:g}')} {cumulative}")
            lines.append(f"{name}_bucket{_fmt(labels, 'le=+Inf')} {count}")
            # +Inf 桶等于总观测数（区间计数已全部落在各桶或 overflow 内）
            lines.append(f"{name}_sum{_fmt(labels)} {_hist_sum[(name, labels)]:.6f}")
            lines.append(f"{name}_count{_fmt(labels)} {count}")
    return "\n".join(lines) + "\n"
