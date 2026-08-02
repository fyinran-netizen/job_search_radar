# Examples

## Example 1: Campus Role With Risk

Input:

```json
{
  "title": "AI软件工程师（2027校园招聘）",
  "requirements": "2027届毕业生；熟悉 Python；有 3 年以上生产系统经验优先。"
}
```

Output:

```json
{
  "canonical_role": "AI Software Engineer",
  "campus_eligible": true,
  "hard_requirements": ["2027 graduate", "Python"],
  "nice_to_have": ["production system experience"],
  "red_flags": [],
  "evidence": {
    "campus_eligible": "Title says 2027校园招聘 and requirements mention 2027届毕业生"
  },
  "confidence": 0.86
}
```
