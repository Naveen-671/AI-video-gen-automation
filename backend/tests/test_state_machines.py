"""Unit tests for Video, Job, and Publish state machines."""

import pytest
from backend.app.domain.state_machines import (
    VideoState,
    JobState,
    PublishAttemptState,
    InvalidStateTransitionError,
    transition_video_state,
    transition_job_state,
    transition_publish_state
)

def test_legal_video_forward_transitions():
    assert transition_video_state(VideoState.IDEA, VideoState.SCRIPTING) == VideoState.SCRIPTING
    assert transition_video_state(VideoState.SCRIPTING, VideoState.STORYBOARD) == VideoState.STORYBOARD
    assert transition_video_state(VideoState.STORYBOARD, VideoState.GENERATING) == VideoState.GENERATING
    assert transition_video_state(VideoState.GENERATING, VideoState.EDITING) == VideoState.EDITING
    assert transition_video_state(VideoState.EDITING, VideoState.QA) == VideoState.QA
    assert transition_video_state(VideoState.QA, VideoState.AWAITING_APPROVAL) == VideoState.AWAITING_APPROVAL
    assert transition_video_state(VideoState.AWAITING_APPROVAL, VideoState.APPROVED) == VideoState.APPROVED
    assert transition_video_state(VideoState.APPROVED, VideoState.SCHEDULED) == VideoState.SCHEDULED
    assert transition_video_state(VideoState.SCHEDULED, VideoState.PUBLISHING) == VideoState.PUBLISHING
    assert transition_video_state(VideoState.PUBLISHING, VideoState.PUBLISHED) == VideoState.PUBLISHED

def test_illegal_video_skip_transitions():
    # Direct jump from IDEA to APPROVED must fail
    with pytest.raises(InvalidStateTransitionError):
        transition_video_state(VideoState.IDEA, VideoState.APPROVED)

    # Jump from SCRIPTING to PUBLISHING must fail
    with pytest.raises(InvalidStateTransitionError):
        transition_video_state(VideoState.SCRIPTING, VideoState.PUBLISHING)

    # Transition out of terminal PUBLISHED must fail
    with pytest.raises(InvalidStateTransitionError):
        transition_video_state(VideoState.PUBLISHED, VideoState.SCRIPTING)

def test_video_rejection_and_edit_backtracking():
    # Rejection sends video back to SCRIPTING, STORYBOARD, or EDITING
    assert transition_video_state(VideoState.AWAITING_APPROVAL, VideoState.REJECTED) == VideoState.REJECTED
    assert transition_video_state(VideoState.REJECTED, VideoState.STORYBOARD) == VideoState.STORYBOARD

    # Input edits on APPROVED or SCHEDULED drops state back to AWAITING_APPROVAL
    assert transition_video_state(VideoState.APPROVED, VideoState.AWAITING_APPROVAL) == VideoState.AWAITING_APPROVAL
    assert transition_video_state(VideoState.SCHEDULED, VideoState.AWAITING_APPROVAL) == VideoState.AWAITING_APPROVAL

def test_video_uncertain_publishing_reconciliation():
    assert transition_video_state(VideoState.PUBLISHING, VideoState.PUBLISH_UNCERTAIN) == VideoState.PUBLISH_UNCERTAIN
    assert transition_video_state(VideoState.PUBLISH_UNCERTAIN, VideoState.RECONCILING) == VideoState.RECONCILING
    # Reconciled successfully -> PUBLISHED
    assert transition_video_state(VideoState.RECONCILING, VideoState.PUBLISHED) == VideoState.PUBLISHED

def test_job_state_transitions():
    # Standard lifecycle
    assert transition_job_state(JobState.QUEUED, JobState.LEASED) == JobState.LEASED
    assert transition_job_state(JobState.LEASED, JobState.RUNNING) == JobState.RUNNING
    assert transition_job_state(JobState.RUNNING, JobState.SUCCEEDED) == JobState.SUCCEEDED

    # Retryable failure
    assert transition_job_state(JobState.RUNNING, JobState.FAILED_RETRYABLE) == JobState.FAILED_RETRYABLE
    assert transition_job_state(JobState.FAILED_RETRYABLE, JobState.QUEUED) == JobState.QUEUED

    # Illegal transition: directly from QUEUED to SUCCEEDED
    with pytest.raises(InvalidStateTransitionError):
        transition_job_state(JobState.QUEUED, JobState.SUCCEEDED)

def test_publish_state_transitions():
    assert transition_publish_state(PublishAttemptState.PENDING, PublishAttemptState.IN_FLIGHT) == PublishAttemptState.IN_FLIGHT
    assert transition_publish_state(PublishAttemptState.IN_FLIGHT, PublishAttemptState.UNCERTAIN) == PublishAttemptState.UNCERTAIN
    assert transition_publish_state(PublishAttemptState.UNCERTAIN, PublishAttemptState.RECONCILING) == PublishAttemptState.RECONCILING
    assert transition_publish_state(PublishAttemptState.RECONCILING, PublishAttemptState.SUCCESS) == PublishAttemptState.SUCCESS
