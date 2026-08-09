# Examples

## Example 1: Chinese JD Page

Input excerpt:

```text
驱动开发工程师（2026校园招聘）
招聘类别：校园招聘
工作地点：江苏省-苏州市
工作职责：负责嵌入式系统、驱动、媒体、传输等相关领域技术开发工作。
任职资格：通信、电子、计算机相关专业，硕士及以上学历；熟悉 C/C++。
现在申请
```

Output:

```json
{
  "page_id": "page-1",
  "page_context": {
    "company_name": null,
    "recruitment_type": "校园招聘",
    "graduation_years": ["2026"],
    "published_at": null,
    "deadline": null
  },
  "jobs": [
    {
      "title": "驱动开发工程师（2026校园招聘）",
      "location": "江苏省-苏州市",
      "description": "负责嵌入式系统、驱动、媒体、传输等相关领域技术开发工作。",
      "requirements": "通信、电子、计算机相关专业，硕士及以上学历；熟悉 C/C++。"
    }
  ]
}
```

## Example 2: Some Positions Have No Location

Input excerpt:

```text
招聘岗位
1. 数据分析师，工作地点为上海，负责经营数据分析。
2. 信息科技岗位，面向应届毕业生，从事信息科技相关工作。
3. 营业网点业务岗位（综合服务），面向应届毕业生，从事柜面及厅堂服务。
```

Output jobs:

```json
[
  {
    "title": "数据分析师",
    "location": "上海",
    "description": "负责经营数据分析",
    "requirements": null
  },
  {
    "title": "信息科技岗位",
    "location": null,
    "description": "从事信息科技相关工作",
    "requirements": "面向应届毕业生"
  },
  {
    "title": "营业网点业务岗位（综合服务）",
    "location": null,
    "description": "从事柜面及厅堂服务",
    "requirements": "面向应届毕业生"
  }
]
```
