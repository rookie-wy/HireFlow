package metrics

import (
	"strings"
	"testing"
)

// TestCounterAndRender 计数器导出为 name_total，标签按字典序稳定输出。
func TestCounterAndRender(t *testing.T) {
	Inc("unit_requests", 1, map[string]string{"method": "GET", "status": "200"})
	Inc("unit_requests", 2, map[string]string{"method": "GET", "status": "200"})
	out := Render()
	if !strings.Contains(out, `unit_requests_total{method="GET",status="200"} 3`) {
		t.Fatalf("计数器输出不符:\n%s", out)
	}
}

// TestHistogramBuckets 直方图必须有累积 bucket、_sum、_count，且 +Inf 等于 count。
func TestHistogramBuckets(t *testing.T) {
	Observe("unit_seconds", 0.3, map[string]string{"route": "/x"})
	Observe("unit_seconds", 5.0, map[string]string{"route": "/x"})
	out := Render()
	for _, want := range []string{
		`unit_seconds_bucket{route="/x",le="0.5"} 1`,
		`unit_seconds_bucket{route="/x",le="8"} 2`,
		`unit_seconds_bucket{route="/x",le="+Inf"} 2`,
		`unit_seconds_count{route="/x"} 2`,
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("缺少 %q\n%s", want, out)
		}
	}
	if !strings.Contains(out, `unit_seconds_sum{route="/x"} 5.3`) {
		t.Fatalf("_sum 不符:\n%s", out)
	}
}

// TestGaugeAndFunc 静态 gauge 与采集时求值的 gauge 都能导出。
func TestGaugeAndFunc(t *testing.T) {
	SetGauge("unit_gauge", 7, nil)
	RegisterGaugeFunc("unit_dynamic", func() float64 { return 42 }, map[string]string{"kind": "db"})
	out := Render()
	if !strings.Contains(out, "unit_gauge 7") {
		t.Fatalf("静态 gauge 缺失:\n%s", out)
	}
	if !strings.Contains(out, `unit_dynamic{kind="db"} 42`) {
		t.Fatalf("动态 gauge 缺失:\n%s", out)
	}
}

// TestTimer Timer 返回的函数调用后应产生一次观测。
func TestTimer(t *testing.T) {
	done := Timer("unit_timer_seconds", nil)
	done()
	out := Render()
	if !strings.Contains(out, "unit_timer_seconds_count 1") {
		t.Fatalf("Timer 未产生观测:\n%s", out)
	}
}

// TestNoDoubleTotalSuffix 名称已带 _total 时不应渲染成 _total_total（Prometheus 命名规范）。
func TestNoDoubleTotalSuffix(t *testing.T) {
	Inc("unit_already_total", 3, nil)
	out := Render()
	if strings.Contains(out, "unit_already_total_total") {
		t.Fatalf("出现双重 _total 后缀:\n%s", out)
	}
	if !strings.Contains(out, "unit_already_total 3") {
		t.Fatalf("计数器未正确导出:\n%s", out)
	}
}
