"""Tests verifying the zero-cost policy and metered provider rejection."""

import pytest
from backend.app.providers.mock_providers import (
    MockLLMProvider,
    MockStillsProvider,
    MockTTSProvider,
    validate_provider_cost_class,
    CostClassViolationError
)

def test_metered_cost_class_rejected():
    with pytest.raises(CostClassViolationError) as exc_info:
        validate_provider_cost_class("metered")
    assert "prohibited" in str(exc_info.value)

def test_mock_providers_reject_metered():
    with pytest.raises(CostClassViolationError):
        MockLLMProvider(cost_class="metered")

    with pytest.raises(CostClassViolationError):
        MockStillsProvider(cost_class="metered")

    with pytest.raises(CostClassViolationError):
        MockTTSProvider(cost_class="metered")

def test_allowed_cost_classes_accepted():
    for cost_class in ("free_local", "free_quota", "manual"):
        assert validate_provider_cost_class(cost_class) is True
