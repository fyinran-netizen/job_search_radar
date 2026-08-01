"""Deterministic job extraction from page text."""

import re
from urllib.parse import urljoin

from job_radar.agents.models import PageContent
from job_radar.extractors.base import JobExtractor
from job_radar.models.job import RawJobRecord


FIELD_ALIASES = {
    "company_name": ["company_name", "公司名称", "招聘单位", "公司"],
    "company_type": ["company_type", "公司性质", "企业性质"],
    "title": ["title", "岗位名称", "职位名称", "职位"],
    "location": ["location", "工作地点", "工作地域", "城市"],
    "description": ["description", "职位描述", "岗位职责", "工作职责", "工作内容"],
    "requirements": ["requirements", "任职资格", "任职要求", "岗位要求", "专业要求"],
    "recruitment_type": ["recruitment_type", "招聘类别", "招聘类型"],
    "graduation_years": ["graduation_years", "毕业年份", "招聘对象"],
    "published_at": ["published_at", "发布时间", "发布日期"],
    "deadline": ["deadline", "截止时间", "报名截止"],
    "apply_url": ["apply_url", "投递链接", "申请链接"],
}


class RuleBasedJobExtractor(JobExtractor):
    """Extract raw jobs from predictable text patterns and common JD sections."""

    def extract(self, page: PageContent) -> list[RawJobRecord]:
        """Extract one or more raw job records from page content."""

        if "---JOB---" in page.text:
            return self._extract_marker_jobs(page)
        return [self._extract_single_job_page(page)]

    def _extract_marker_jobs(self, page: PageContent) -> list[RawJobRecord]:
        records: list[RawJobRecord] = []
        for block in page.text.split("---JOB---"):
            parsed = self._parse_key_value_block(block)
            if not parsed:
                continue
            self._apply_page_defaults(parsed, page)
            records.append(RawJobRecord.model_validate(parsed))
        return records

    def _extract_single_job_page(self, page: PageContent) -> RawJobRecord:
        text = self._clean_text(page.text)
        metadata = page.metadata
        parsed = self._parse_labelled_fields(text)

        description = self._extract_section(
            text,
            ["工作职责", "岗位职责", "职位描述", "工作内容"],
            ["任职资格", "任职要求", "岗位要求", "专业要求", "学历要求"],
        ) or parsed.get("description")
        requirements = self._extract_section(
            text,
            ["任职资格", "任职要求", "岗位要求", "专业要求", "学历要求"],
            ["现在申请", "立即申请", "返回职位列表", "投递", "公司简介"],
        ) or parsed.get("requirements")
        recruitment_type = self._normalize_recruitment_type(parsed.get("recruitment_type")) or self._infer_recruitment_type(text)

        record_data = {
            "company_name": parsed.get("company_name")
            or metadata.get("company_name")
            or self._infer_company_name(page.source_name, page.title),
            "company_type": parsed.get("company_type") or metadata.get("company_type"),
            "title": parsed.get("title") or self._infer_title(text, page.title),
            "location": parsed.get("location") or self._find_after_labels(text, ["工作地点", "工作地域"]),
            "description": description,
            "requirements": requirements,
            "recruitment_type": recruitment_type,
            "graduation_years": self._extract_graduation_years(text),
            "published_at": self._normalize_date(parsed.get("published_at") or self._find_after_labels(text, ["发布时间"])),
            "deadline": self._normalize_date(parsed.get("deadline") or self._find_after_labels(text, ["截止时间"])),
            "apply_url": parsed.get("apply_url") or self._pick_apply_url(page),
            "source_url": page.url,
            "source_name": page.source_name,
            "is_official": bool(metadata.get("is_official", False)),
        }
        return RawJobRecord.model_validate(record_data)

    def _parse_key_value_block(self, block: str) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip()
        if not parsed:
            return {}
        if "graduation_years" in parsed and isinstance(parsed["graduation_years"], str):
            parsed["graduation_years"] = self._split_years(str(parsed["graduation_years"]))
        if "is_official" in parsed:
            parsed["is_official"] = str(parsed["is_official"]).lower() in {"true", "1", "yes"}
        return parsed

    def _parse_labelled_fields(self, text: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for field_name, aliases in FIELD_ALIASES.items():
            value = self._find_after_labels(text, aliases)
            if value:
                parsed[field_name] = value
        return parsed

    @staticmethod
    def _apply_page_defaults(parsed: dict[str, object], page: PageContent) -> None:
        parsed.setdefault("source_url", page.url)
        parsed.setdefault("source_name", page.source_name)
        parsed.setdefault("company_name", page.metadata.get("company_name"))
        parsed.setdefault("company_type", page.metadata.get("company_type"))
        parsed.setdefault("is_official", page.metadata.get("is_official", False))

    @staticmethod
    def _clean_text(text: str) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _split_years(value: str) -> list[str]:
        return re.findall(r"20\d{2}", value)

    def _extract_graduation_years(self, text: str) -> list[str]:
        return sorted(set(self._split_years(text)))

    @staticmethod
    def _normalize_date(value: str | None) -> str | None:
        if not value:
            return None
        match = re.search(r"(20\d{2})[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?", value)
        if not match:
            return value.strip()
        year = match.group(1)
        month = int(match.group(2))
        day = int(match.group(3) or 1)
        return f"{year}-{month:02d}-{day:02d}"

    @staticmethod
    def _normalize_recruitment_type(value: str | None) -> str | None:
        if not value:
            return None
        if "校园招聘" in value or "校招" in value:
            return "Campus Recruitment"
        if "实习" in value:
            return "Internship"
        return value.strip()

    def _infer_recruitment_type(self, text: str) -> str | None:
        return self._normalize_recruitment_type(text)

    def _infer_title(self, text: str, page_title: str) -> str | None:
        metadata_title = self._find_title_before_metadata(text)
        if metadata_title:
            return metadata_title

        candidates = [*text.splitlines()[:30], page_title]
        for candidate in candidates:
            cleaned = self._strip_title_noise(candidate)
            if cleaned and self._looks_like_job_title(cleaned):
                return cleaned
        return candidates[0].strip() if candidates else None

    @staticmethod
    def _strip_title_noise(value: str) -> str:
        text = re.sub(r"[-_]{1,2}.*$", "", value).strip()
        return text.replace("招聘详细", "").replace("职位详情", "").strip()

    def _find_title_before_metadata(self, text: str) -> str | None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        metadata_labels = {"招聘类别：", "招聘类别:", "工作性质：", "工作性质:", "薪资范围：", "薪资范围:"}
        for index, line in enumerate(lines):
            if line not in metadata_labels:
                continue
            for candidate in reversed(lines[:index]):
                cleaned = self._strip_title_noise(candidate)
                if self._looks_like_job_title(cleaned):
                    return cleaned
        return None

    @staticmethod
    def _looks_like_job_title(value: str) -> bool:
        if not value or len(value) > 80:
            return False
        noise_words = {
            "首页",
            "社会招聘",
            "校园招聘",
            "实习生招聘",
            "联系我们",
            "内部推荐",
            "个人中心",
            "退出",
            "登录",
            "注册",
            "热招职位",
            "长招职位",
        }
        if value in noise_words or "招聘系统" in value:
            return False
        return any(keyword in value for keyword in ["工程师", "分析", "产品", "开发", "算法", "运营", "管培", "Graduate"])

    @staticmethod
    def _infer_company_name(source_name: str, page_title: str) -> str | None:
        for text in [source_name, page_title]:
            match = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）()·]+(?:公司|银行|集团|科技|有限公司))", text)
            if match:
                return match.group(1)
        return source_name or None

    @staticmethod
    def _find_after_labels(text: str, labels: list[str]) -> str | None:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*[：:]\s*(.+)"
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_section(text: str, start_labels: list[str], end_labels: list[str]) -> str | None:
        for start_label in start_labels:
            start_match = re.search(rf"{re.escape(start_label)}\s*[：:]?", text)
            if not start_match:
                continue
            start = start_match.end()
            end = len(text)
            for end_label in end_labels:
                end_match = re.search(rf"\n\s*{re.escape(end_label)}\s*[：:]?", text[start:])
                if end_match:
                    end = min(end, start + end_match.start())
            section = text[start:end].strip()
            if section:
                return section
        return None

    @staticmethod
    def _pick_apply_url(page: PageContent) -> str | None:
        links = page.metadata.get("links", [])
        if not isinstance(links, list):
            return page.url
        for link in links:
            if not isinstance(link, dict):
                continue
            text = str(link.get("text", ""))
            href = str(link.get("href", ""))
            if any(keyword in text + href for keyword in ["申请", "投递", "apply", "Apply"]):
                return urljoin(page.url, href)
        return page.url
