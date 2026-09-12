// Package metrics 极简进程内指标注册表（Prometheus 文本格式导出）。
//
// 设计取舍：不引入 prometheus/client_golang —— 本项目单实例、指标量小，
// 固定桶直方图 + 计数器 + 可回调 gauge 已足够，避免为埋点增加依赖与构建风险。
// 需要高级能力（Summary/Histogram 原生分位、多进程聚合）时再换官方客户端。
package metrics

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// Buckets 直方图桶（秒）：覆盖 5ms ~ 10min，够看 HTTP 与筛选任务耗时。
var Buckets = []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34, 60, 120, 300, 600}

// GaugeFunc 采集时动态求值的 gauge（如连接池状态）。
type GaugeFunc func() float64

type key struct {
	name   string
	labels string
}

type histogram struct {
	count    uint64
	sum      float64
	buckets  []uint64 // 每个桶的**区间**计数（非累积）
	overflow uint64   // 超过最大桶边界的观测数（归入 +Inf）
}

var (
	mu         sync.RWMutex
	counters   = map[key]float64{}
	histograms = map[key]*histogram{}
	gauges     = map[key]float64{}
	gaugeFuncs = map[key]GaugeFunc{}
)

func labelString(labels map[string]string) string {
	if len(labels) == 0 {
		return ""
	}
	keys := make([]string, 0, len(labels))
	for k := range labels {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, fmt.Sprintf("%s=%q", k, labels[k]))
	}
	return "{" + strings.Join(parts, ",") + "}"
}

// Inc 计数器自增（value 可为负，用于"当前进行中"这类 gauge 语义时请改用 SetGauge）。
func Inc(name string, value float64, labels map[string]string) {
	mu.Lock()
	counters[key{name, labelString(labels)}] += value
	mu.Unlock()
}

// Observe 直方图观测（单位：秒）。
func Observe(name string, seconds float64, labels map[string]string) {
	k := key{name, labelString(labels)}
	mu.Lock()
	h := histograms[k]
	if h == nil {
		h = &histogram{buckets: make([]uint64, len(Buckets))}
		histograms[k] = h
	}
	h.count++
	h.sum += seconds
	// 只累加到**第一个**满足 seconds<=edge 的桶（区间计数），
	// 渲染时再做累积（cumulative）——早先把"落在哪些桶"直接当累积输出，导致 bucket 值大于 count。
	placed := false
	for i, edge := range Buckets {
		if seconds <= edge {
			h.buckets[i]++
			placed = true
			break
		}
	}
	if !placed {
		h.overflow++
	}
	mu.Unlock()
}

// SetGauge 设置瞬时值。
func SetGauge(name string, value float64, labels map[string]string) {
	mu.Lock()
	gauges[key{name, labelString(labels)}] = value
	mu.Unlock()
}

// RegisterGaugeFunc 注册采集时求值的 gauge（例如 DB 连接池、队列长度）。
func RegisterGaugeFunc(name string, fn GaugeFunc, labels map[string]string) {
	mu.Lock()
	gaugeFuncs[key{name, labelString(labels)}] = fn
	mu.Unlock()
}

// Timer 返回一个函数，调用即观测一次耗时：
//
//	done := metrics.Timer("x_seconds", nil); defer done()
func Timer(name string, labels map[string]string) func() {
	start := time.Now()
	return func() { Observe(name, time.Since(start).Seconds(), labels) }
}

// Render 导出 Prometheus 文本格式。
func Render() string {
	mu.RLock()
	defer mu.RUnlock()

	var b strings.Builder
	// 计数器
	cKeys := make([]key, 0, len(counters))
	for k := range counters {
		cKeys = append(cKeys, k)
	}
	sort.Slice(cKeys, func(i, j int) bool {
		if cKeys[i].name != cKeys[j].name {
			return cKeys[i].name < cKeys[j].name
		}
		return cKeys[i].labels < cKeys[j].labels
	})
	for _, k := range cKeys {
		// 计数器统一以 _total 结尾；名字里已带 _total 的不再重复追加
		// （Prometheus 规范：_total 是计数器专用后缀，双后缀会让告警规则写不准）
		name := k.name
		if !strings.HasSuffix(name, "_total") {
			name += "_total"
		}
		fmt.Fprintf(&b, "%s%s %g\n", name, k.labels, counters[k])
	}
	// gauge（静态 + 回调）
	gKeys := make([]key, 0, len(gauges)+len(gaugeFuncs))
	for k := range gauges {
		gKeys = append(gKeys, k)
	}
	for k := range gaugeFuncs {
		gKeys = append(gKeys, k)
	}
	sort.Slice(gKeys, func(i, j int) bool {
		if gKeys[i].name != gKeys[j].name {
			return gKeys[i].name < gKeys[j].name
		}
		return gKeys[i].labels < gKeys[j].labels
	})
	for _, k := range gKeys {
		if fn, ok := gaugeFuncs[k]; ok {
			fmt.Fprintf(&b, "%s%s %g\n", k.name, k.labels, fn())
			continue
		}
		fmt.Fprintf(&b, "%s%s %g\n", k.name, k.labels, gauges[k])
	}
	// 直方图
	hKeys := make([]key, 0, len(histograms))
	for k := range histograms {
		hKeys = append(hKeys, k)
	}
	sort.Slice(hKeys, func(i, j int) bool {
		if hKeys[i].name != hKeys[j].name {
			return hKeys[i].name < hKeys[j].name
		}
		return hKeys[i].labels < hKeys[j].labels
	})
	for _, k := range hKeys {
		h := histograms[k]
		cumulative := uint64(0)
		for i, edge := range Buckets {
			cumulative += h.buckets[i] // 区间计数 → 累积
			le := labelWith(k.labels, "le", fmt.Sprintf("%g", edge))
			fmt.Fprintf(&b, "%s_bucket%s %d\n", k.name, le, cumulative)
		}
		cumulative += h.overflow
		fmt.Fprintf(&b, "%s_bucket%s %d\n", k.name, labelWith(k.labels, "le", "+Inf"), cumulative)
		fmt.Fprintf(&b, "%s_sum%s %g\n", k.name, k.labels, h.sum)
		fmt.Fprintf(&b, "%s_count%s %d\n", k.name, k.labels, h.count)
	}
	return b.String()
}

// labelWith 在已有标签串里追加一个标签。
func labelWith(labels, k, v string) string {
	if labels == "" {
		return fmt.Sprintf("{%s=%q}", k, v)
	}
	return strings.TrimSuffix(labels, "}") + fmt.Sprintf(",%s=%q}", k, v)
}
