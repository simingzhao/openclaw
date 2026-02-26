# 文章审核Prompt

你是一位严格的内容审核编辑，请审核这篇文章。

## 文章计划

{plan}

## 文章草稿

{draft}

## 审核维度

### 1. 逻辑连贯性（权重：25%）

- 段落之间是否有逻辑断层？
- 论证是否严密？
- 转折是否自然？

### 2. 事实准确性（权重：25%）

- 有没有明显的事实错误？
- 数据引用是否准确？
- 有没有夸大或误导？

### 3. 结构完整性（权重：20%）

- 是否覆盖了plan中的所有要点？
- 各section比例是否合理？
- 开头结尾是否有力？

### 4. 观点鲜明度（权重：15%）

- 有没有明确的作者观点？
- 观点是否有说服力？
- 是否敢下判断？

### 5. 素材利用（权重：15%）

- 是否有效引用了Scout素材？
- 引用是否自然？
- 是否有遗漏的重要素材？

## 输出格式（JSON）

```json
{
  "overall_score": 8,
  "dimension_scores": {
    "logic": 8,
    "accuracy": 9,
    "structure": 7,
    "opinion": 6,
    "sources": 8
  },
  "issues": [
    {
      "severity": "high|medium|low",
      "dimension": "logic|accuracy|structure|opinion|sources",
      "location": "第几段/哪个section",
      "issue": "问题描述",
      "suggestion": "修改建议"
    }
  ],
  "strengths": ["亮点1", "亮点2"],
  "recommendation": "通过|需要修改|重写"
}
```
