package service

import "testing"

// TestApplyBoost 个性化调分：两位小数、边界钳制、零偏置恒等。
func TestApplyBoost(t *testing.T) {
	s := &FeedbackService{}
	cases := []struct {
		name  string
		score float64
		boost float64
		want  float64
	}{
		{"零偏置恒等", 87.2, 0, 87.2},
		{"正偏置两位小数", 72.4, 0.1, 79.64},
		{"正偏置四舍五入", 87.2, 0.05, 91.56},
		{"负偏置两位小数", 72.4, -0.05, 68.78},
		{"上界钳制", 98, 0.15, 100},
		{"下界钳制", 1, -1.5, 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := s.ApplyBoost(c.score, c.boost)
			if got != c.want {
				t.Fatalf("ApplyBoost(%v, %v) = %v, want %v", c.score, c.boost, got, c.want)
			}
			// 断言不出现浮点噪声：乘以 100 后必须是整数
			if scaled := got * 100; scaled != float64(int64(scaled+0.5)) {
				t.Fatalf("ApplyBoost(%v, %v) = %v 含浮点噪声", c.score, c.boost, got)
			}
		})
	}
}
