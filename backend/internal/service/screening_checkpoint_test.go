package service

import (
	"testing"

	"github.com/ai-recruitment/backend/internal/agenttypes"
	"github.com/ai-recruitment/backend/internal/repository"
)

// report 构造断点报告（含 agent 细节与讨论记录，验证序列化不丢信息）。
func report(cid string, score float64, withDiscussion bool) agenttypes.OverallReport {
	r := agenttypes.OverallReport{
		CandidateID:        cid,
		OverallScore:       score,
		DimensionScores:    map[string]float64{"skill": score, "stability": 90},
		RecommendationText: "推荐进入面试",
		Evidence:           []string{"五年 Python 经验"},
		AgentDetails: []agenttypes.AgentEvaluationResult{
			{Agent: "interviewer", Score: score, Confidence: 0.8, Evidence: []string{"证据A"}},
		},
	}
	if withDiscussion {
		r.Discussion = map[string]any{"turns": []any{map[string]any{"round": 1, "agent": "interviewer"}}}
	}
	return r
}

// TestMergeCheckpointVerdictsAddsAll 断点报告应全部并入缓存，且信息不丢。
func TestMergeCheckpointVerdictsAddsAll(t *testing.T) {
	verdicts := map[string]repository.CachedVerdict{}
	added := mergeCheckpointVerdicts(verdicts, []agenttypes.OverallReport{
		report("c1", 88.5, true),
		report("c2", 61.0, false),
	})
	if added != 2 || len(verdicts) != 2 {
		t.Fatalf("应并入 2 条，实际 added=%d len=%d", added, len(verdicts))
	}
	v := verdicts["c1"]
	if v.OverallScore != 88.5 || v.RecommendationText != "推荐进入面试" || len(v.Evidence) != 1 {
		t.Fatalf("断点结论字段丢失: %+v", v)
	}
	if v.ProfileHash != "" {
		t.Fatal("断点条目指纹应为空（表示来自父任务断点，允许直接命中）")
	}
	if _, ok := v.Discussion["agent_details"]; !ok {
		t.Fatal("agent_details 应并入 discussion_json（供审计回放）")
	}
	if _, ok := v.Discussion["turns"]; !ok {
		t.Fatal("原有 discussion 内容不应被覆盖")
	}
}

// TestMergeCheckpointVerdictsKeepsExisting DB 缓存优先：已在缓存里的候选人不被断点覆盖。
func TestMergeCheckpointVerdictsKeepsExisting(t *testing.T) {
	verdicts := map[string]repository.CachedVerdict{
		"c1": {OverallScore: 99.9, ProfileHash: "hash-abc"},
	}
	added := mergeCheckpointVerdicts(verdicts, []agenttypes.OverallReport{report("c1", 10.0, false)})
	if added != 0 {
		t.Fatalf("已存在条目不应被断点覆盖，added=%d", added)
	}
	if verdicts["c1"].OverallScore != 99.9 || verdicts["c1"].ProfileHash != "hash-abc" {
		t.Fatal("DB 缓存（带指纹）必须保留，否则会绕过'简历是否变更'的判断")
	}
}

// TestMergeCheckpointVerdictsEmpty 空断点不应改动任何状态。
func TestMergeCheckpointVerdictsEmpty(t *testing.T) {
	verdicts := map[string]repository.CachedVerdict{}
	if added := mergeCheckpointVerdicts(verdicts, nil); added != 0 || len(verdicts) != 0 {
		t.Fatalf("空断点应为 no-op，added=%d len=%d", added, len(verdicts))
	}
}
