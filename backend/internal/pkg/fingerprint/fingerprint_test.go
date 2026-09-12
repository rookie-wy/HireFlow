package fingerprint

import "testing"

// TestOfStableAcrossKeyOrder 指纹必须与 map 遍历顺序无关（否则每次重启进程都会判成"简历已变更"）。
func TestOfStableAcrossKeyOrder(t *testing.T) {
	a := map[string]interface{}{"name": "张伟", "email": "z@example.com", "skills": []interface{}{"Python", "Redis"}}
	b := map[string]interface{}{"skills": []interface{}{"Redis", "Python"}, "email": "z@example.com", "name": "张伟"}
	if Of("resume text", a) != Of("resume text", b) {
		t.Fatal("指纹不稳定：技能顺序/键顺序不同导致结果不一致")
	}
}

// TestOfChangesWithContent 简历内容变化必须导致指纹变化（否则会错误复用旧结论）。
func TestOfChangesWithContent(t *testing.T) {
	base := map[string]interface{}{"name": "张伟", "skills": []interface{}{"Python"}}
	h1 := Of("resume v1", base)
	if h1 == Of("resume v2", base) {
		t.Fatal("原文变化未反映到指纹")
	}
	changed := map[string]interface{}{"name": "张伟", "skills": []interface{}{"Python", "Go"}}
	if h1 == Of("resume v1", changed) {
		t.Fatal("结构化字段变化未反映到指纹")
	}
}

// TestOfFormat 指纹长度固定 32（DB 列 64 足够，日志里可安全取前 8 位）。
func TestOfFormat(t *testing.T) {
	h := Of("x", nil)
	if len(h) != 32 {
		t.Fatalf("指纹长度应为 32，实际 %d", len(h))
	}
	if h != Of("x", nil) {
		t.Fatal("同一输入两次计算应一致")
	}
}

// TestJobConfigChangesInvalidateCache 岗位配置指纹：权重/参数/JD 任一变化都必须改变指纹。
func TestJobConfigChangesInvalidateCache(t *testing.T) {
	jd := map[string]interface{}{"hard_requirements": []interface{}{"本科"}, "job_category": "tech"}
	base := JobConfig(jd, map[string]interface{}{"interviewer": 0.5, "skill_evaluator": 0.5}, nil)

	if base != JobConfig(jd, map[string]interface{}{"skill_evaluator": 0.5, "interviewer": 0.5}, nil) {
		t.Fatal("键顺序不同不应改变配置指纹")
	}
	if base == JobConfig(jd, map[string]interface{}{"interviewer": 0.7, "skill_evaluator": 0.3}, nil) {
		t.Fatal("权重变化必须改变配置指纹（否则改了权重仍复用旧结论）")
	}
	if base == JobConfig(jd, nil, map[string]interface{}{"rag_top_k": 12}) {
		t.Fatal("检索参数变化必须改变配置指纹")
	}
	if base == JobConfig(map[string]interface{}{"job_category": "general"}, map[string]interface{}{"interviewer": 0.5, "skill_evaluator": 0.5}, nil) {
		t.Fatal("JD 变化必须改变配置指纹")
	}
}
