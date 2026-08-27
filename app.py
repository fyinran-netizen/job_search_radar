"""Streamlit entry point for Job Radar."""

from __future__ import annotations

from typing import Iterable

from pydantic import ValidationError
import streamlit as st

from job_radar.config import load_profile
from job_radar.models.decisions import AgentRunResult
from job_radar.models.job import APPLICATION_STATUSES
from job_radar.models.profile import UserProfile
from job_radar.pipeline.runner import PipelineResult
from job_radar.services.ingestion_service import IngestionService
from job_radar.services.job_service import JobService
from job_radar.utils.paths import CONFIG_DIR, DEFAULT_DB_PATH

EDUCATION_OPTIONS = [
    "Master's student or recent graduate",
    "Bachelor's student or recent graduate",
    "PhD student or recent graduate",
    "Experienced professional",
]
ROLE_OPTIONS = [
    "Data Analyst",
    "Business Analyst",
    "Software Engineer",
    "Data Engineer",
    "Machine Learning Engineer",
    "Product Manager",
    "Graduate Program",
    "Technology Graduate Analyst",
]
SKILL_OPTIONS = [
    "Python",
    "SQL",
    "Pandas",
    "Data Analysis",
    "Machine Learning",
    "Excel",
    "Tableau",
    "Power BI",
    "Testing",
    "Distributed Systems",
    "Stakeholder Communication",
]
COMPANY_TYPE_OPTIONS = [
    "Bank",
    "State-owned Enterprise",
    "Technology",
    "Foreign Enterprise",
    "Consulting",
    "FinTech",
    "Internet",
    "Manufacturing",
]
LOCATION_OPTIONS = [
    "Shanghai",
    "Beijing",
    "Shenzhen",
    "Guangzhou",
    "Hangzhou",
    "Suzhou",
    "Sydney",
    "Melbourne",
    "Singapore",
    "Remote",
]
GRADUATION_MONTH_OPTIONS = [
    f"{year}-{month:02d}"
    for year in range(2025, 2032)
    for month in range(1, 13)
]


def render_app() -> None:
    """Render the Job Radar Streamlit application."""

    st.set_page_config(page_title="Job Radar", layout="wide")
    st.title("Job Radar")
    st.caption("Local job discovery, matching, and application tracking")

    ingestion_service = IngestionService(db_path=DEFAULT_DB_PATH, enable_codex_ai=True)
    job_service = JobService(DEFAULT_DB_PATH)
    default_profile, _, _ = load_profile(CONFIG_DIR)

    real_result_slot = st.container()
    profile = render_profile_form(default_profile)
    if profile is not None:
        with real_result_slot:
            run_real_pipeline(ingestion_service, profile)

    with st.expander("Testing tools"):
        st.caption("Uses mock tools for development checks only.")
        if st.button("Run mock agent search", icon=":material/bug_report:"):
            result, notices, agent_result = ingestion_service.run_mock_agent_pipeline(default_profile)
            render_notices(notices)
            render_agent_result(agent_result)
            render_pipeline_result(result)

    render_jobs(job_service)


def render_profile_form(default_profile: UserProfile) -> UserProfile | None:
    """Render the real-search profile form and return a validated profile on submit."""

    st.subheader("Real search")
    with st.form("real_search_profile"):
        education_options = _option_pool(EDUCATION_OPTIONS, [default_profile.education])
        education = st.selectbox(
            "Education",
            options=education_options,
            index=education_options.index(default_profile.education) if default_profile.education in education_options else 0,
        )
        graduation_date = st.select_slider(
            "Graduation month",
            options=GRADUATION_MONTH_OPTIONS,
            value=_default_graduation_month(default_profile.graduation_date),
        )
        target_roles = st.multiselect(
            "Target roles",
            options=_option_pool(ROLE_OPTIONS, default_profile.target_roles),
            default=default_profile.target_roles,
        )
        additional_roles = st.text_input("Additional target roles", placeholder="Comma separated")
        skills = st.multiselect(
            "Skills",
            options=_option_pool(SKILL_OPTIONS, default_profile.skills),
            default=default_profile.skills,
        )
        additional_skills = st.text_input("Additional skills", placeholder="Comma separated")
        preferred_company_types = st.multiselect(
            "Preferred company types",
            options=_option_pool(COMPANY_TYPE_OPTIONS, default_profile.preferred_company_types),
            default=default_profile.preferred_company_types,
        )
        preferred_locations = st.multiselect(
            "Preferred locations",
            options=_option_pool(LOCATION_OPTIONS, default_profile.preferred_locations),
            default=default_profile.preferred_locations,
        )
        excluded_locations = st.multiselect(
            "Excluded locations",
            options=_option_pool(LOCATION_OPTIONS, default_profile.excluded_locations),
            default=default_profile.excluded_locations,
        )
        submitted = st.form_submit_button("Run real search", type="primary", icon=":material/search:")

    if not submitted:
        return None

    try:
        return UserProfile.model_validate(
            {
                "education": education,
                "graduation_date": graduation_date,
                "target_roles": _merge_items(target_roles, _split_items(additional_roles)),
                "skills": _merge_items(skills, _split_items(additional_skills)),
                "preferred_company_types": preferred_company_types,
                "preferred_locations": preferred_locations,
                "excluded_locations": excluded_locations,
            }
        )
    except ValidationError as exc:
        st.error("Profile input is invalid.")
        st.json(exc.errors())
        return None


def run_real_pipeline(ingestion_service: IngestionService, profile: UserProfile) -> None:
    """Run the real pipeline and render its result."""

    try:
        with st.spinner("Running real search..."):
            result, notices, agent_result = ingestion_service.run_real_search_pipeline(profile)
    except Exception as exc:
        st.error("Real search failed.")
        st.exception(exc)
        return

    render_notices(notices)
    render_agent_result(agent_result)
    render_pipeline_result(result)
    st.success("Real search finished.")


def render_jobs(job_service: JobService) -> None:
    """Render persisted jobs and editable user status fields."""

    st.subheader("Jobs")
    frame = job_service.jobs_dataframe()
    if frame.empty:
        st.info("No jobs saved yet. Run real search or the mock agent test.")
        return

    edited = st.data_editor(
        frame,
        key="jobs_editor",
        hide_index=True,
        disabled=[
            "id",
            "company",
            "company type",
            "title",
            "location",
            "match score",
            "match reasons",
            "missing requirements",
            "apply link",
            "source",
        ],
        column_config={
            "status": st.column_config.SelectboxColumn("Status", options=APPLICATION_STATUSES),
            "notes": st.column_config.TextColumn("Notes"),
            "apply link": st.column_config.LinkColumn("Apply link"),
        },
    )

    if st.button("Save status and notes", icon=":material/save:"):
        for row in edited.to_dict(orient="records"):
            job_service.update_status_and_notes(
                job_id=int(row["id"]),
                status=str(row["status"]),
                notes="" if row["notes"] is None else str(row["notes"]),
            )
        st.success("Status and notes saved.")
        st.rerun()

    st.download_button(
        "Export CSV",
        data=edited.drop(columns=["id"]).to_csv(index=False).encode("utf-8-sig"),
        file_name="job_radar_export.csv",
        mime="text/csv",
        icon=":material/download:",
    )


def render_pipeline_result(result: PipelineResult) -> None:
    """Render common pipeline metrics and errors."""

    cols = st.columns(7)
    cols[0].metric("Collected", result.collected_count)
    cols[1].metric("Valid", result.valid_count)
    cols[2].metric("Invalid", result.invalid_count)
    cols[3].metric("Duplicates", result.duplicate_count)
    cols[4].metric("Inserted", result.inserted_count)
    cols[5].metric("Updated", result.updated_count)
    cols[6].metric("Failed", result.failed_count)
    if result.errors:
        st.error("Some records reported errors.")
        st.dataframe(result.errors, hide_index=True)


def render_agent_result(agent_result: AgentRunResult) -> None:
    """Render agent decisions and tool trace."""

    if not agent_result.profile_check.is_complete:
        st.warning("Profile is incomplete.")
        st.write(agent_result.profile_check.model_dump())
        return

    with st.container(border=True):
        st.write("Search plan", agent_result.search_plan.model_dump() if agent_result.search_plan else {})
        st.write("Selected sources", [source.model_dump() for source in agent_result.selected_sources])
        if agent_result.errors:
            st.error("Some sources could not be collected or extracted.")
            st.dataframe(agent_result.errors, hide_index=True)
        if agent_result.tool_events:
            st.write("Tool events", [event.model_dump() for event in agent_result.tool_events])


def render_notices(notices: Iterable[str]) -> None:
    """Render run notices."""

    for notice in notices:
        st.info(notice)


def _split_items(value: str) -> list[str]:
    normalized = value.replace(",", "\n").replace(";", "\n")
    return [item.strip() for item in normalized.splitlines() if item.strip()]


def _merge_items(*groups: list[str]) -> list[str]:
    merged = []
    seen = set()
    for group in groups:
        for item in group:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _option_pool(base_options: list[str], selected_values: list[str]) -> list[str]:
    return _merge_items(base_options, [value for value in selected_values if value])


def _default_graduation_month(value: str) -> str:
    if value in GRADUATION_MONTH_OPTIONS:
        return value
    year = value[:4] if len(value) >= 4 else ""
    fallback = f"{year}-06"
    if fallback in GRADUATION_MONTH_OPTIONS:
        return fallback
    return "2026-06"


if __name__ == "__main__":
    render_app()
