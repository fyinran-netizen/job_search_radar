"""Streamlit entry point for Job Radar."""

from __future__ import annotations

import streamlit as st

from job_radar.models.job import APPLICATION_STATUSES
from job_radar.services.ingestion_service import IngestionService
from job_radar.services.job_service import JobService
from job_radar.utils.paths import DEFAULT_DB_PATH


def render_app() -> None:
    """Render the Job Radar Streamlit application."""

    st.set_page_config(page_title="Job Radar", layout="wide")
    st.title("Job Radar")
    st.caption("Local job discovery and application tracking tool")

    ingestion_service = IngestionService(DEFAULT_DB_PATH)
    job_service = JobService(DEFAULT_DB_PATH)

    st.subheader("Demo Pipeline")
    if st.button("Load demo jobs", type="primary"):
        result, notices = ingestion_service.run_demo_pipeline()
        for notice in notices:
            st.info(notice)
        render_pipeline_result(result)

    st.subheader("Mock Agent Pipeline")
    st.caption("Runs the LLM and web tool abstractions with deterministic local mocks. No network requests are made.")
    if st.button("Run mock agent search"):
        result, notices, agent_result = ingestion_service.run_mock_agent_pipeline()
        for notice in notices:
            st.info(notice)
        if agent_result.profile_check.is_complete:
            st.write("Search plan", agent_result.search_plan.model_dump() if agent_result.search_plan else {})
            st.write(
                "Selected sources",
                [source.model_dump() for source in agent_result.selected_sources],
            )
            st.write(
                "Tool events",
                [event.model_dump() for event in agent_result.tool_events],
            )
        else:
            st.warning("Profile is incomplete.")
            st.write(agent_result.profile_check.model_dump())
        render_pipeline_result(result)

    st.subheader("Manual URL Pipeline")
    st.caption("Uses enabled URLs from sources config, fetches pages with Python, then runs backend extraction.")
    if st.button("Fetch manual source URL"):
        result, notices, agent_result = ingestion_service.run_manual_source_pipeline()
        for notice in notices:
            st.info(notice)
        if agent_result.selected_sources:
            st.write(
                "Selected sources",
                [source.model_dump() for source in agent_result.selected_sources],
            )
        if agent_result.errors:
            st.error("Some manual sources could not be collected or extracted.")
            st.dataframe(agent_result.errors, hide_index=True)
        if agent_result.tool_events:
            st.write("Tool events", [event.model_dump() for event in agent_result.tool_events])
        render_pipeline_result(result)

    st.subheader("Jobs")
    frame = job_service.jobs_dataframe()
    if frame.empty:
        st.info("No jobs saved yet. Click Load demo jobs to run the local pipeline.")
        return

    edited = st.data_editor(
        frame,
        key="jobs_editor",
        hide_index=True,
        disabled=[
            "id",
            "公司",
            "公司类型",
            "岗位",
            "地点",
            "匹配度",
            "匹配原因",
            "缺失要求",
            "投递链接",
            "来源",
        ],
        column_config={
            "状态": st.column_config.SelectboxColumn("状态", options=APPLICATION_STATUSES),
            "备注": st.column_config.TextColumn("备注"),
            "投递链接": st.column_config.LinkColumn("投递链接"),
        },
    )

    if st.button("Save status and notes"):
        for row in edited.to_dict(orient="records"):
            job_service.update_status_and_notes(
                job_id=int(row["id"]),
                status=str(row["状态"]),
                notes="" if row["备注"] is None else str(row["备注"]),
            )
        st.success("Status and notes saved.")
        st.rerun()

    st.download_button(
        "Export CSV",
        data=edited.drop(columns=["id"]).to_csv(index=False).encode("utf-8-sig"),
        file_name="job_radar_export.csv",
        mime="text/csv",
    )


def render_pipeline_result(result) -> None:
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
    else:
        st.success("Pipeline completed without invalid records.")


if __name__ == "__main__":
    render_app()
