"""Profile builder boundary for future resume/user-note extraction."""

from job_radar.profile.models import UserProfile


def merge_profile_updates(base: UserProfile, updates: dict[str, object]) -> UserProfile:
    """Return a profile with non-empty update fields applied."""

    clean_updates = {key: value for key, value in updates.items() if value not in (None, "", [])}
    return base.model_copy(update=clean_updates)
