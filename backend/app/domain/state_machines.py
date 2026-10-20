"""State machine definitions, transition tables, and invariants."""

from enum import Enum
from typing import Set, Dict, Optional

class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass

class VideoState(str, Enum):
    IDEA = "IDEA"
    SCRIPTING = "SCRIPTING"
    STORYBOARD = "STORYBOARD"
    GENERATING = "GENERATING"
    EDITING = "EDITING"
    QA = "QA"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    
    # Side & Exception states
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PUBLISH_UNCERTAIN = "PUBLISH_UNCERTAIN"
    RECONCILING = "RECONCILING"

# Legal forward and backward transitions for Video
LEGAL_VIDEO_TRANSITIONS: Dict[VideoState, Set[VideoState]] = {
    VideoState.IDEA: {VideoState.SCRIPTING, VideoState.CANCELLED},
    VideoState.SCRIPTING: {VideoState.STORYBOARD, VideoState.FAILED, VideoState.CANCELLED},
    VideoState.STORYBOARD: {VideoState.GENERATING, VideoState.FAILED, VideoState.CANCELLED},
    VideoState.GENERATING: {VideoState.EDITING, VideoState.FAILED, VideoState.CANCELLED},
    VideoState.EDITING: {VideoState.QA, VideoState.FAILED, VideoState.CANCELLED},
    VideoState.QA: {VideoState.AWAITING_APPROVAL, VideoState.EDITING, VideoState.FAILED},
    VideoState.AWAITING_APPROVAL: {VideoState.APPROVED, VideoState.REJECTED, VideoState.CANCELLED},
    VideoState.REJECTED: {VideoState.SCRIPTING, VideoState.STORYBOARD, VideoState.EDITING, VideoState.CANCELLED},
    VideoState.APPROVED: {VideoState.SCHEDULED, VideoState.PUBLISHING, VideoState.AWAITING_APPROVAL, VideoState.CANCELLED},
    VideoState.SCHEDULED: {VideoState.PUBLISHING, VideoState.AWAITING_APPROVAL, VideoState.CANCELLED},
    VideoState.PUBLISHING: {VideoState.PUBLISHED, VideoState.PUBLISH_UNCERTAIN, VideoState.FAILED},
    VideoState.PUBLISH_UNCERTAIN: {VideoState.RECONCILING},
    VideoState.RECONCILING: {VideoState.PUBLISHED, VideoState.APPROVED, VideoState.FAILED},
    VideoState.PUBLISHED: set(), # Terminal state
    VideoState.CANCELLED: set(), # Terminal state
    VideoState.FAILED: {VideoState.SCRIPTING, VideoState.STORYBOARD, VideoState.GENERATING, VideoState.EDITING, VideoState.CANCELLED}
}

class JobState(str, Enum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    CANCELLED = "CANCELLED"

LEGAL_JOB_TRANSITIONS: Dict[JobState, Set[JobState]] = {
    JobState.QUEUED: {JobState.LEASED, JobState.CANCELLED},
    JobState.LEASED: {JobState.RUNNING, JobState.QUEUED, JobState.CANCELLED},
    JobState.RUNNING: {
        JobState.SUCCEEDED,
        JobState.FAILED_RETRYABLE,
        JobState.FAILED_PERMANENT,
        JobState.NEEDS_HUMAN,
        JobState.CANCELLED
    },
    JobState.FAILED_RETRYABLE: {JobState.QUEUED, JobState.FAILED_PERMANENT},
    JobState.SUCCEEDED: set(),
    JobState.FAILED_PERMANENT: set(),
    JobState.NEEDS_HUMAN: {JobState.QUEUED, JobState.CANCELLED},
    JobState.CANCELLED: set()
}

class PublishAttemptState(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    SUCCESS = "SUCCESS"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    UNCERTAIN = "UNCERTAIN"
    RECONCILING = "RECONCILING"
    FAILED_PERMANENT = "FAILED_PERMANENT"

LEGAL_PUBLISH_TRANSITIONS: Dict[PublishAttemptState, Set[PublishAttemptState]] = {
    PublishAttemptState.PENDING: {PublishAttemptState.IN_FLIGHT, PublishAttemptState.FAILED_PERMANENT},
    PublishAttemptState.IN_FLIGHT: {
        PublishAttemptState.SUCCESS,
        PublishAttemptState.FAILED_RETRYABLE,
        PublishAttemptState.UNCERTAIN,
        PublishAttemptState.FAILED_PERMANENT
    },
    PublishAttemptState.FAILED_RETRYABLE: {PublishAttemptState.PENDING, PublishAttemptState.FAILED_PERMANENT},
    PublishAttemptState.UNCERTAIN: {PublishAttemptState.RECONCILING},
    PublishAttemptState.RECONCILING: {PublishAttemptState.SUCCESS, PublishAttemptState.FAILED_RETRYABLE, PublishAttemptState.FAILED_PERMANENT},
    PublishAttemptState.SUCCESS: set(),
    PublishAttemptState.FAILED_PERMANENT: set()
}

def transition_video_state(current_state: VideoState, target_state: VideoState) -> VideoState:
    """Validates and applies a video state transition."""
    allowed = LEGAL_VIDEO_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal video transition from {current_state.value} to {target_state.value}. Allowed: {[s.value for s in allowed]}"
        )
    return target_state

def transition_job_state(current_state: JobState, target_state: JobState) -> JobState:
    """Validates and applies a job state transition."""
    allowed = LEGAL_JOB_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal job transition from {current_state.value} to {target_state.value}. Allowed: {[s.value for s in allowed]}"
        )
    return target_state

def transition_publish_state(current_state: PublishAttemptState, target_state: PublishAttemptState) -> PublishAttemptState:
    """Validates and applies a publish attempt transition."""
    allowed = LEGAL_PUBLISH_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal publish transition from {current_state.value} to {target_state.value}. Allowed: {[s.value for s in allowed]}"
        )
    return target_state
