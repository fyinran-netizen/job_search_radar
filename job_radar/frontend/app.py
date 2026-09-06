"""Streamlit entry point for Job Radar."""

from __future__ import annotations

import re

from pydantic import ValidationError
import streamlit as st

from job_radar.config import load_profile
from job_radar.services.agent_service import (
    AgentService,
    AgentServiceResult,
    CheckpointHistoryEntry,
    create_rule_based_real_agent_service,
)
from job_radar.tools.job_extraction.models import APPLICATION_STATUSES
from job_radar.profile.models import UserProfile
from job_radar.frontend.job_service import JobService
from job_radar.frontend.view_models import checkpoint_history_rows
from job_radar.infra.paths import CONFIG_DIR, DEFAULT_DB_PATH

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

    agent_service = create_rule_based_real_agent_service(db_path=DEFAULT_DB_PATH)
    job_service = JobService(DEFAULT_DB_PATH)
    default_profile, _, _ = load_profile(CONFIG_DIR)

    real_result_slot = st.container()
    profile = render_profile_form(default_profile)
    if profile is not None:
        with real_result_slot:
            run_agent_pipeline(agent_service, profile)

    with st.expander("Testing tools"):
        st.caption("Uses mock tools for development checks only.")
        if st.button("Run mock agent search", icon=":material/bug_report:"):
            st.info("The agent runtime is configured for the RuleBasedController; use the profile form to run it.")

    render_checkpoint_debug(agent_service)
    render_jobs(job_service)


def render_profile_form(default_profile: UserProfile) -> UserProfile | None:
    """Render the real-search profile form and return a validated profile on submit."""

    st.subheader("Real search")
    st.checkbox(
        "单步调试",
        value=True,
        key="pause_after_action",
        help="每执行一个 action 后暂停，点击调试区域中的按钮继续。",
    )
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
        return UserProfile.from_form_data(
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


def run_agent_pipeline(agent_service: AgentService, profile: UserProfile) -> None:
    """Run the agent service and render its result."""

    try:
        with st.spinner("Running real search..."):
            result = agent_service.run(
                profile,
                pause_after_action=bool(st.session_state.get("pause_after_action", True)),
            )
    except Exception as exc:
        st.error("Real search failed.")
        st.exception(exc)
        return

    st.session_state["agent_service_result"] = result
    st.session_state["agent_run_id"] = result.run_id
    render_agent_service_result(result)
    if result.interrupted:
        st.info("工作流已暂停，请在 Checkpoint debugging 区域执行下一个 action。")
    else:
        st.success("Rule-based agent search finished.")


def render_agent_service_result(result: AgentServiceResult) -> None:
    """Render the agent state and controller trace."""

    st.write("Final state", result.state.model_dump())
    st.write(
        "Decision trace",
        [entry.model_dump() for entry in result.decision_trace],
    )


def render_checkpoint_debug(agent_service: AgentService) -> None:
    """Render checkpoint loading, inspection, resume, and replay controls."""

    result = st.session_state.get("agent_service_result")
    current_run_id = st.session_state.get("agent_run_id")
    if not isinstance(current_run_id, str):
        current_run_id = result.run_id if isinstance(result, AgentServiceResult) else None

    with st.expander("Checkpoint debugging"):
        loaded_run_id = st.text_input(
            "Load existing run",
            value=current_run_id or "",
            key="checkpoint_run_id_input",
            placeholder="Enter run_id",
        ).strip()
        if st.button("Load run", key="load_checkpoint_run"):
            if not _valid_run_id(loaded_run_id):
                st.error("Invalid run_id format.")
                return
            try:
                loaded_history = agent_service.state_history(loaded_run_id)
            except Exception as exc:
                st.error("Unable to load run history.")
                st.exception(exc)
                return
            if not loaded_history:
                st.error(f"No checkpoints found for run_id `{loaded_run_id}`.")
                return
            st.session_state["agent_run_id"] = loaded_run_id
            current_run_id = loaded_run_id

        if not current_run_id:
            st.info("Run a search or enter an existing run_id to inspect checkpoints.")
            return

        st.caption(f"run_id: `{current_run_id}`")
        try:
            history = agent_service.state_history(current_run_id)
        except Exception as exc:
            st.error("Unable to read checkpoint history.")
            st.exception(exc)
            return

        if not history:
            st.error(f"No checkpoints found for run_id `{current_run_id}`.")
            return

        latest_entry = history[0]
        st.caption(f"checkpoint_id: `{latest_entry.checkpoint_id or '(none)'}`")
        st.write("Checkpoint summary", {
            "round_index": latest_entry.round_index,
            "stop_reason": latest_entry.stop_reason,
            "counts": latest_entry.state_counts,
        })
        can_resume = bool(latest_entry.next_nodes)
        if can_resume and st.button("\u6267\u884c\u4e0b\u4e00\u4e2a action", key="resume_agent_action"):
            try:
                resumed = agent_service.resume(current_run_id, pause_after_action=True)
                st.session_state["agent_service_result"] = resumed
                st.session_state["agent_run_id"] = current_run_id
                st.rerun()
            except Exception as exc:
                st.error("\u6267\u884c\u4e0b\u4e00\u4e2a action \u5931\u8d25\u3002")
                st.exception(exc)
        if isinstance(result, AgentServiceResult) and result.run_id == current_run_id:
            st.write("Latest result summary", _agent_state_summary(result.state))
        st.dataframe(checkpoint_history_rows(history), hide_index=True, width="stretch")
        checkpoint_ids = [entry.checkpoint_id for entry in history]
        selected_for_view = st.selectbox(
            "View checkpoint",
            checkpoint_ids,
            index=0,
            format_func=lambda value: f"{value[:12]}...",
            key="view_checkpoint",
        )
        try:
            viewed_entry = agent_service.checkpoint_detail(current_run_id, selected_for_view)
        except Exception as exc:
            st.error("Unable to load checkpoint details.")
            st.exception(exc)
            return
        _render_checkpoint_state(viewed_entry)

        selected_for_replay = st.selectbox(
            "Replay next action",
            checkpoint_ids,
            index=0,
            format_func=lambda value: f"{value[:12]}...",
            key="replay_checkpoint_selector",
        )
        if st.button("Replay selected checkpoint", key="replay_checkpoint"):
            try:
                replayed = agent_service.replay_from_checkpoint(current_run_id, selected_for_replay)
                st.session_state["agent_service_result"] = replayed
                st.session_state["agent_run_id"] = current_run_id
                st.success(f"Replay completed at checkpoint `{replayed.checkpoint_id}`.")
                st.rerun()
            except Exception as exc:
                st.error("Checkpoint replay failed.")
                st.exception(exc)


def _valid_run_id(value: str) -> bool:
    """Accept generated IDs and safe user-supplied thread IDs."""

    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value))


def _render_checkpoint_state(entry: CheckpointHistoryEntry) -> None:
    """Render all useful fields from one immutable checkpoint snapshot."""

    state = entry.state
    if state is None:
        st.error("Checkpoint details were not loaded.")
        return
    st.caption(f"Viewing checkpoint `{entry.checkpoint_id}` from {entry.created_at or 'unknown time'}")
    st.json({
        "round_index": state.round_index,
        "stop_reason": state.stop_reason,
        "last_search_outcome": state.last_search_outcome,
        "notices": state.notices,
    })
    with st.expander("search_plan", expanded=True):
        st.json(state.search_plan.model_dump(mode="json") if state.search_plan else {})

    list_fields = (
        "query_history", "executed_queries", "search_round_results",
        "candidate_sources", "selected_sources", "acquired_pages",
        "job_detail_pages", "pending_followups", "rejected_pages", "page_analysis_traces", "prepared_jobs",
        "understanding_records", "match_assessments", "errors",
    )
    for field_name in list_fields:
        value = getattr(state, field_name)
        with st.expander(field_name, expanded=True):
            if field_name == "search_round_results":
                st.json(_json_value(value))
            elif field_name in {"acquired_pages", "job_detail_pages"}:
                st.dataframe(_checkpoint_page_rows(value), hide_index=True, width="stretch")
            elif value and isinstance(value[0], dict):
                st.dataframe(value, hide_index=True, width="stretch")
            elif value and hasattr(value[0], "model_dump"):
                st.dataframe([item.model_dump(mode="json") for item in value], hide_index=True, width="stretch")
            elif value:
                st.dataframe({field_name: value}, hide_index=True, width="stretch")
            else:
                st.info("No data in this checkpoint.")


def _checkpoint_page_rows(value: list[object]) -> list[dict[str, object]]:
    """Summarize page payloads without sending their body text to Streamlit."""

    rows: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            page = item
        elif hasattr(item, "model_dump"):
            page = item.model_dump(mode="python")
        else:
            page = {}
        html = page.get("html")
        visible_text = page.get("visible_text")
        fetch_evidence = page.get("fetch_evidence") or {}
        rows.append({
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "source_name": page.get("source_name", ""),
            "acquisition_method": page.get("acquisition_method") or fetch_evidence.get("fetch_method", ""),
            "html_length": len(html) if isinstance(html, str) else 0,
            "visible_text_length": len(visible_text) if isinstance(visible_text, str) else 0,
        })
    return rows


def _agent_state_summary(state: object) -> dict[str, object]:
    if not hasattr(state, "round_index"):
        return {}
    return {
        "round_index": state.round_index,
        "stop_reason": state.stop_reason,
        "counts": {
            field_name: len(getattr(state, field_name))
            for field_name in (
                "candidate_sources", "selected_sources", "acquired_pages", "job_detail_pages",
                "prepared_jobs", "understanding_records", "match_assessments", "errors",
            )
        },
    }


def _json_value(value: object) -> object:
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


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
            "locations",
            "match score",
            "match reasons",
            "missing requirements",
            "source url",
            "source",
        ],
        column_config={
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=APPLICATION_STATUSES,
            ),
            "notes": st.column_config.TextColumn("Notes"),
            "source url": st.column_config.LinkColumn("Source URL"),
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


