"""Streamlit entry point for Job Radar."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError
import streamlit as st

from job_radar.config import load_profile
from job_radar.agent.action_names import AGENT_ACTION_NAMES
from job_radar.agent.controllers.context import build_scheduling_context
from job_radar.agent.controllers.features import build_scheduling_features
from job_radar.agent.controllers.scheduler import ACTION_PROFILES
from job_radar.agent.controllers.scoring import score_available_actions
from job_radar.agent.policies.availability import available_actions
from job_radar.services.agent_service import (
    AgentService,
    AgentServiceResult,
    CheckpointHistoryEntry,
)
from job_radar.services.runtime import create_real_agent_runtime
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

    runtime = create_real_agent_runtime()
    agent_service = AgentService(
        executor=runtime.executor,
        db_path=DEFAULT_DB_PATH,
    )
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
            st.info("The agent runtime uses the deterministic scheduler; use the profile form to run it.")

    render_checkpoint_debug(agent_service)
    render_jobs(job_service)
    render_scheduler_decision_showcase(agent_service)


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
        st.success("Agent search finished.")


def render_agent_service_result(result: AgentServiceResult) -> None:
    """Render a compact, showcase-oriented view of one completed run."""

    state = result.state
    st.divider()
    st.subheader("Run Summary")
    _render_run_summary(state)

    st.subheader("Execution Flow")
    _render_execution_flow(result)

    st.subheader("Final Match Results")
    _render_match_results(state)

    st.subheader("Pipeline / Funnel Summary")
    _render_pipeline_funnel(state)

    with st.expander("Technical details"):
        _render_technical_details(state)


def _render_run_summary(state: object) -> None:
    """Render the small set of metrics useful in a demo or screenshot."""

    metrics = [
        ("Search rounds", getattr(state, "search_round_count", 0)),
        ("Candidate sources", len(getattr(state, "candidate_sources", []))),
        ("Acquired pages", len(getattr(state, "acquired_pages", []))),
        ("Job detail pages", len(getattr(state, "job_detail_pages", []))),
        ("Prepared jobs", len(getattr(state, "prepared_jobs", []))),
        ("Understanding records", len(getattr(state, "understanding_records", []))),
        ("Match assessments", len(getattr(state, "match_assessments", []))),
        ("Errors", len(getattr(state, "errors", []))),
    ]
    columns = st.columns(4)
    for index, (label, value) in enumerate(metrics):
        with columns[index % len(columns)]:
            st.metric(label, value)

    stop_reason = getattr(state, "stop_reason", None)
    if stop_reason:
        st.info(f"**Stop reason:** {_readable_stop_reason(stop_reason)}")
    else:
        st.caption("Stop reason: run is still in progress or paused at a checkpoint.")


def _render_execution_flow(result: AgentServiceResult) -> None:
    """Show the actual selected action sequence, including dynamic branches."""

    if not result.decision_trace:
        st.info("No actions have been recorded yet.")
        return

    for index, entry in enumerate(result.decision_trace, start=1):
        action = entry.selected_action.replace("_", " ").title()
        rationale = entry.rationale.strip()
        marker = "●" if index == len(result.decision_trace) else "○"
        st.markdown(f"**{marker} {index}. {action}**")
        if rationale:
            st.caption(rationale)
        if index < len(result.decision_trace):
            st.markdown("<div style='border-left: 2px solid #d9d9d9; height: 12px; margin-left: 7px;'></div>", unsafe_allow_html=True)


def _render_match_results(state: object) -> None:
    """Render readable job cards from persisted prepared jobs and assessments."""

    jobs_by_key = {
        job.deduplication_key: job
        for job in getattr(state, "prepared_jobs", [])
        if getattr(job, "deduplication_key", None)
    }
    assessments = getattr(state, "match_assessments", [])
    if not assessments:
        st.info("No final match assessments were produced in this run.")
        return

    for item in assessments:
        assessment = item.get("assessment", {}) if isinstance(item, dict) else {}
        key = item.get("deduplication_key") if isinstance(item, dict) else None
        job = jobs_by_key.get(key)
        title = (getattr(job, "title", None) if job else None) or item.get("title", "Untitled role")
        company = (getattr(job, "company_name", None) if job else None) or item.get("company_name", "Unknown company")
        score = assessment.get("match_score")
        recommendation = assessment.get("recommendation")
        reasons = assessment.get("match_reasons") or assessment.get("deterministic_reasons") or []
        apply_url = (getattr(job, "apply_url", None) if job else None) or (getattr(job, "source_url", None) if job else None)

        with st.container(border=True):
            header, score_column = st.columns([4, 1])
            with header:
                st.markdown(f"### {title}")
                st.caption(company)
            with score_column:
                st.metric("Match score", f"{score}/100" if score is not None else "—")
            if recommendation:
                st.markdown(f"**Recommendation:** {_readable_recommendation(recommendation)}")
            if reasons:
                st.markdown("**Why it matches**")
                for reason in reasons[:4]:
                    st.markdown(f"- {reason}")
            if apply_url:
                st.link_button("Open application / source", apply_url)


def _render_pipeline_funnel(state: object) -> None:
    stages = [
        ("Candidate sources", len(getattr(state, "candidate_sources", []))),
        ("Acquired pages", len(getattr(state, "acquired_pages", []))),
        ("Job detail pages", len(getattr(state, "job_detail_pages", []))),
        ("Prepared jobs", len(getattr(state, "prepared_jobs", []))),
        ("Understanding records", len(getattr(state, "understanding_records", []))),
        ("Final matches", len(getattr(state, "match_assessments", []))),
    ]
    columns = st.columns(len(stages))
    for index, (label, value) in enumerate(stages):
        with columns[index]:
            st.metric(label, value)
            if index < len(stages) - 1:
                st.caption("→")


def _render_technical_details(state: object) -> None:
    fields = (
        "selected_sources", "acquired_pages", "job_detail_pages",
        "page_analysis_traces", "prepared_jobs", "understanding_records",
    )
    for field_name in fields:
        value = getattr(state, field_name, [])
        with st.expander(field_name.replace("_", " ").title()):
            _render_debug_value(value, field_name)

    with st.expander("Match assessments and errors"):
        _render_debug_value(getattr(state, "match_assessments", []), "match_assessments")
        errors = getattr(state, "errors", [])
        if errors:
            st.markdown("**Errors**")
            _render_debug_value(errors, "errors")


def _render_debug_value(value: object, field_name: str) -> None:
    """Render diagnostics compactly while keeping large payloads out of the main view."""

    if not value:
        st.caption("No data")
        return
    if field_name in {"acquired_pages", "job_detail_pages"}:
        rows = _checkpoint_page_rows(value)
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        return
    if isinstance(value, list) and hasattr(value[0], "model_dump"):
        st.dataframe(_compact_rows([item.model_dump(mode="json") for item in value]), hide_index=True, width="stretch")
    elif isinstance(value, list) and isinstance(value[0], dict):
        st.dataframe(_compact_rows(value), hide_index=True, width="stretch")
    else:
        st.json(_json_value(value))


def _readable_stop_reason(value: str) -> str:
    labels = {
        "max_results": "the hard result cap was reached",
        "max_steps": "the execution safety budget was exhausted",
        "no_progress": "no productive work remained",
        "frontier_exhausted": "the available work frontier was exhausted",
        "max_search_rounds": "the search-round expansion limit was reached",
        "max_rounds": "the search-round expansion limit was reached",
    }
    return labels.get(value, value.replace("_", " "))


def _readable_recommendation(value: str) -> str:
    return {
        "apply": "Apply",
        "consider": "Consider",
        "low_priority": "Low priority",
        "skip": "Skip",
    }.get(value, value.replace("_", " ").title())


def _compact_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop columns that contain no useful value across a debug table."""

    if not rows:
        return rows
    columns = [key for key in rows[0] if any(row.get(key) not in (None, "", [], {}) for row in rows)]
    return [{key: row.get(key) for key in columns} for row in rows]


def _showcase_display_value(value: object) -> str:
    """Make generic showcase key/value cells safe for Streamlit Arrow tables."""

    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


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
            "search_round_count": latest_entry.search_round_count,
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
        _render_scheduler_frontier(viewed_entry, agent_service)

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
        "search_round_count": state.search_round_count,
        "stop_reason": state.stop_reason,
        "last_search_outcome": state.last_search_outcome
    })
    with st.expander("search_plan", expanded=True):
        st.json(state.search_plan.model_dump(mode="json") if state.search_plan else {})

    list_fields = (
        "query_history", "executed_queries", "search_round_results",
        "candidate_sources", "selected_sources", "acquired_pages",
        "job_detail_pages", "pending_followups", "explored_followup_links", "followup_resolutions", "rejected_pages", "page_analysis_traces", "prepared_jobs",
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


_FRONTIER_ACTIONS = (
    "acquire_page",
    "analyze_page",
    "job_extraction",
    "explore_followups",
    "job_understanding",
    "match_analysis",
)


def _render_scheduler_frontier(entry: CheckpointHistoryEntry, agent_service: AgentService) -> None:
    """Render compact queue readiness without exposing page or job payloads."""

    if entry.state is None:
        return

    context = build_scheduling_context(
        entry.state,
        agent_service.limits,
        list(_FRONTIER_ACTIONS),
    )
    rows = []
    for action in _FRONTIER_ACTIONS:
        backlog = context.specific.backlogs[action]
        rows.append({
            "action": action,
            "pending": backlog.pending,
            "executable": backlog.executable,
            "batch_size": backlog.batch_size,
            "backlog_to_batch_ratio": round(backlog.batch_fill_ratio, 2),
            # This is the presentation-level queue readiness signal.  It
            # deliberately does not alter or duplicate backend availability.
            "available": bool(backlog.executable and entry.state.stop_reason is None),
            "uses_llm": ACTION_PROFILES[action].uses_llm,
            "uses_network": ACTION_PROFILES[action].uses_network,
        })

    st.subheader("Scheduler Frontier")
    st.dataframe(rows, hide_index=True, width="stretch")


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
    if not hasattr(state, "search_round_count"):
        return {}
    return {
        "search_round_count": state.search_round_count,
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


def render_scheduler_decision_showcase(agent_service: AgentService) -> None:
    """Render an end-of-page, screenshot-friendly scheduler decision audit."""

    with st.expander("Scheduler Decision Showcase", expanded=False):
        run_id = st.session_state.get("agent_run_id")
        if not isinstance(run_id, str) or not run_id:
            st.info("Load a run to inspect its scheduler decision.")
            return

        try:
            history = agent_service.state_history(run_id)
        except Exception as exc:
            st.error("Unable to load scheduler checkpoint data.")
            st.exception(exc)
            return
        if not history:
            st.info("No checkpoints are available for this run.")
            return

        checkpoint_id = st.session_state.get("view_checkpoint") or history[0].checkpoint_id
        if checkpoint_id not in {item.checkpoint_id for item in history}:
            checkpoint_id = history[0].checkpoint_id
        try:
            entry = agent_service.checkpoint_detail(run_id, checkpoint_id)
        except Exception as exc:
            st.error("Unable to load the selected scheduler checkpoint.")
            st.exception(exc)
            return
        if entry.state is None:
            st.info("The selected checkpoint has no state payload.")
            return

        trace_entry, trace_index = _showcase_trace_entry(run_id, entry)
        available = list(trace_entry.available_actions) if trace_entry else available_actions(entry.state, agent_service.limits)
        context = build_scheduling_context(entry.state, agent_service.limits, available)
        frontier_context = build_scheduling_context(entry.state, agent_service.limits, list(AGENT_ACTION_NAMES))
        features = build_scheduling_features(entry.state, agent_service.limits, context)
        computed_scores = score_available_actions(context, features)
        score_rows = _showcase_score_rows(trace_entry, computed_scores)
        score_by_action = {row["action"]: row["total"] for row in score_rows}
        selected_action = trace_entry.selected_action if trace_entry else None

        st.caption(f"Run `{run_id}` · checkpoint `{entry.checkpoint_id}`")
        _render_showcase_frontier(frontier_context, score_by_action, selected_action, entry.state, available)
        _render_showcase_decision_summary(
            entry,
            context,
            features,
            selected_action,
            score_by_action.get(selected_action) if selected_action else None,
        )
        _render_showcase_score_breakdown(score_rows, selected_action)
        _render_showcase_features(features)
        _render_showcase_transition(agent_service, history, entry, trace_index, trace_entry)


def _render_showcase_frontier(context, score_by_action, selected_action, state, available) -> None:
    rows = []
    for action in AGENT_ACTION_NAMES:
        backlog = context.specific.backlogs.get(action)
        executable = backlog.executable if backlog else 0
        batch_size = backlog.batch_size if backlog else 0
        ratio = executable / batch_size if batch_size else 0.0
        profile = ACTION_PROFILES[action]
        rows.append({
            "action": action,
            "pending": backlog.pending if backlog else 0,
            "executable": executable,
            "batch_size": batch_size,
            "backlog_to_batch_ratio": round(ratio, 2),
            "available": action in available,
            "uses_llm": profile.uses_llm,
            "uses_network": profile.uses_network,
            "action_score": score_by_action.get(action),
            "selected": action == selected_action,
        })
    st.markdown("**1. Scheduler Frontier**")
    st.dataframe(rows, hide_index=True, width="stretch")


def _render_showcase_decision_summary(entry, context, features, selected_action, selected_score) -> None:
    goal = features.goal
    values = [
        ("search_round_count", entry.state.search_round_count),
        ("execution_step_count", entry.state.execution_step_count),
        ("selected_action", selected_action or "—"),
        ("selected_score", selected_score if selected_score is not None else "—"),
        ("stop_reason", _readable_stop_reason(entry.state.stop_reason) if entry.state.stop_reason else "—"),
        ("remaining_search_rounds", context.common.budget.search_rounds_remaining),
        ("result_count", goal.total_match_assessments),
        ("result_deficit", goal.result_deficit),
    ]
    st.markdown("**2. Selected Decision Summary**")
    columns = st.columns(4)
    for index, (label, value) in enumerate(values):
        with columns[index % len(columns)]:
            st.metric(label.replace("_", " ").title(), value)


def _showcase_score_rows(trace_entry, computed_scores):
    """Prefer recorded trace values, falling back to the deterministic projection."""

    if trace_entry and trace_entry.action_scores:
        rows = []
        for item in trace_entry.action_scores:
            components = item.get("components", {})
            if components:
                for component, value in components.items():
                    rows.append({"action": item.get("action"), "total": item.get("total"), "component": component, "value": value})
            else:
                rows.append({"action": item.get("action"), "total": item.get("total"), "component": "(none)", "value": 0})
        return rows
    rows = []
    for score in computed_scores:
        if score.components:
            for component, value in score.components.items():
                rows.append({"action": score.action, "total": score.total, "component": component, "value": value})
        else:
            rows.append({"action": score.action, "total": score.total, "component": "(none)", "value": 0})
    return rows


def _render_showcase_score_breakdown(score_rows, selected_action) -> None:
    st.markdown("**3. Score Breakdown**")
    if not score_rows:
        st.caption("No score trace is available for this checkpoint.")
        return
    rows = [dict(row, selected=row["action"] == selected_action) for row in score_rows]
    st.dataframe(rows, hide_index=True, width="stretch")


def _render_showcase_features(features) -> None:
    st.markdown("**4. Key Scheduling Signals**")
    rows = []
    for section, values in features.model_dump(mode="json").items():
        _flatten_showcase_values(section, values, rows)
    if rows:
        for row in rows:
            row["value"] = _showcase_display_value(row.get("value"))
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("No scheduling features are available.")


def _flatten_showcase_values(prefix, value, rows) -> None:
    if value is None or value == {} or value == []:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten_showcase_values(f"{prefix}.{key}", item, rows)
        return
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    rows.append({"signal": prefix, "value": value})


def _render_showcase_transition(agent_service, history, entry, trace_index, trace_entry) -> None:
    st.markdown("**5. Decision / State Transition**")
    previous_action = None
    if trace_index is not None and trace_index > 0:
        result = st.session_state.get("agent_service_result")
        if isinstance(result, AgentServiceResult):
            previous_action = result.decision_trace[trace_index - 1].selected_action
    rows = [
        {"field": "previous_action", "value": previous_action or "—"},
        {"field": "selected_action", "value": trace_entry.selected_action if trace_entry else "—"},
        {"field": "next_node", "value": ", ".join(entry.next_nodes) if entry.next_nodes else "(complete)"},
        {"field": "search_round_count", "value": entry.state.search_round_count},
    ]
    parent_id = entry.parent_checkpoint_id
    if parent_id:
        try:
            parent = agent_service.checkpoint_detail(entry.run_id, parent_id)
        except Exception:
            parent = None
        if parent and parent.state:
            rows.append({"field": "search_round_count_before", "value": parent.state.search_round_count})
            for field_name in ("candidate_sources", "acquired_pages", "job_detail_pages", "prepared_jobs", "understanding_records", "match_assessments", "errors"):
                before = len(getattr(parent.state, field_name))
                after = len(getattr(entry.state, field_name))
                if before != after:
                    rows.append({"field": f"{field_name}_delta", "value": after - before})
    for row in rows:
        row["value"] = _showcase_display_value(row.get("value"))
    st.dataframe(rows, hide_index=True, width="stretch")


def _showcase_trace_entry(run_id, entry):
    result = st.session_state.get("agent_service_result")
    if not isinstance(result, AgentServiceResult) or result.run_id != run_id or not result.decision_trace:
        return None, None
    if result.state == entry.state:
        return result.decision_trace[-1], len(result.decision_trace) - 1
    target_round = entry.state.search_round_count
    candidates = [
        (index, item)
        for index, item in enumerate(result.decision_trace)
        if item.state_summary.get("search_round_count") == target_round
    ]
    if candidates:
        index, item = candidates[-1]
        return item, index
    return None, None


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
