// Package fingerprint 候选人画像指纹：用于判断"同一份简历"是否已被精筛过。
package fingerprint

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"sort"
)

// Of 计算简历指纹：基于简历原文 + 结构化字段（技能排序后参与，避免顺序抖动导致指纹变化）。
// 用途：重复筛选时命中缓存直接复用精筛结论，不再重复调用 LLM。
func Of(resumeText string, structured map[string]interface{}) string {
	h := sha256.New()
	h.Write([]byte(resumeText))
	h.Write([]byte{0x1f})
	h.Write([]byte(canonicalStructured(structured)))
	return hex.EncodeToString(h.Sum(nil))[:32]
}

// canonicalStructured 生成稳定的结构化字段表示（键排序 + 技能数组排序）。
func canonicalStructured(structured map[string]interface{}) string {
	if structured == nil {
		return "{}"
	}
	out := make(map[string]interface{}, len(structured))
	for k, v := range structured {
		if skills, ok := v.([]interface{}); ok && k == "skills" {
			sorted := make([]string, 0, len(skills))
			for _, s := range skills {
				sorted = append(sorted, toStr(s))
			}
			sort.Strings(sorted)
			out[k] = sorted
			continue
		}
		out[k] = v
	}
	data, err := json.Marshal(out)
	if err != nil {
		return "{}"
	}
	return string(data)
}

func toStr(v interface{}) string {
	if s, ok := v.(string); ok {
		return s
	}
	data, err := json.Marshal(v)
	if err != nil {
		return ""
	}
	return string(data)
}


// JobConfig 计算岗位配置指纹：参与筛选决策的所有可配置项。
// 任一变化都会让幂等缓存失效（否则会出现"改了权重但分数不变"的错误复用）。
func JobConfig(jdJSON map[string]interface{}, weightsOverride, screenOverrides map[string]interface{}) string {
	payload := map[string]interface{}{
		"jd":       canonicalStructured(jdJSON),
		"weights":  canonicalStructured(weightsOverride),
		"screen":   canonicalStructured(screenOverrides),
	}
	return Of("job-config-v1", payload)
}
