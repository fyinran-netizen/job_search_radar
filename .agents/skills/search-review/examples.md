# Examples

## Example 1: Continue Search

Input:

```json
{
  "target_valid_jobs": 20,
  "valid_jobs": 12,
  "source_coverage": {"state_owned_company_careers": 0, "technology_company_careers": 8, "third_party_boards": 4},
  "current_round": 2,
  "max_rounds": 4,
  "previous_queries": ["2027届 AI应用工程师 校招 上海"]
}
```

Output:

```json
{
  "continue_search": true,
  "reason": "有效岗位不足，且国企/央企来源尚未覆盖。",
  "adjustments": {
    "add_sources": ["state_owned_company_careers"],
    "add_queries": ["央企 2027届 AI 校招", "国企 科技岗 2027届 校园招聘"]
  },
  "next_round_priority": "补充国企和央企官网岗位"
}
```

## Example 2: Stop Search

Input:

```json
{
  "target_valid_jobs": 20,
  "valid_jobs": 24,
  "current_round": 3,
  "max_rounds": 4,
  "high_match_jobs": 10
}
```

Output:

```json
{
  "continue_search": false,
  "reason": "有效岗位数量已超过目标，且已有足够高匹配岗位。",
  "adjustments": {},
  "next_round_priority": null
}
```
