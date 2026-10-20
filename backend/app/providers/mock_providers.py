"""Mocked AI providers adhering to the zero-cost rule and schema validation."""

from typing import Dict, Any, List
from backend.app.config import ALLOWED_COST_CLASSES, DISALLOWED_DEFAULT_COST_CLASSES
from backend.app.domain.models import LLMProposal

class CostClassViolationError(Exception):
    """Raised when an unapproved or metered cost class provider is invoked."""
    pass

def validate_provider_cost_class(cost_class: str) -> bool:
    if cost_class in DISALLOWED_DEFAULT_COST_CLASSES or cost_class not in ALLOWED_COST_CLASSES:
        raise CostClassViolationError(
            f"Provider cost class '{cost_class}' is prohibited. Only {ALLOWED_COST_CLASSES} are permitted under zero-cost rules."
        )
    return True

class MockLLMProvider:
    """Mock LLM provider producing Pydantic-validated proposals (never raw actions)."""
    
    def __init__(self, cost_class: str = "free_quota"):
        validate_provider_cost_class(cost_class)
        self.cost_class = cost_class

    def generate_script_proposal(self, topic: str) -> LLMProposal:
        return LLMProposal(
            proposal_type="SCRIPT_OUTLINE",
            topic=topic,
            suggested_hook=f"Did you know the secret behind {topic}?",
            narrative_points=[
                f"First, {topic} starts with fundamental physical principles.",
                f"Next, modern engineering optimizes {topic} for maximum efficiency.",
                "Finally, here is how you can apply this concept today."
            ],
            suggested_visual_prompts=[
                f"Dynamic cinematic macro shot illustrating {topic}",
                "Infographic cross-section with neon motion arrows",
                "Presenter looking at camera with clean studio background"
            ],
            confidence_score=0.92
        )

class MockStillsProvider:
    """Mock image provider for synthetic still generation."""
    
    def __init__(self, cost_class: str = "free_local"):
        validate_provider_cost_class(cost_class)
        self.cost_class = cost_class

    def generate_still(self, prompt: str, scene_index: int) -> Dict[str, Any]:
        return {
            "scene_index": scene_index,
            "prompt": prompt,
            "width": 1080,
            "height": 1920,
            "synthetic_asset_id": f"mock_still_scene_{scene_index}",
            "cost_class": self.cost_class
        }

class MockTTSProvider:
    """Mock speech synthesis provider."""
    
    def __init__(self, cost_class: str = "free_local"):
        validate_provider_cost_class(cost_class)
        self.cost_class = cost_class

    def synthesize(self, text: str, language: str = "en") -> Dict[str, Any]:
        # Estimate duration: ~150 words per minute -> 2.5 words per second
        word_count = len(text.split())
        est_duration = max(3.0, round(word_count / 2.5, 2))
        return {
            "language": language,
            "word_count": word_count,
            "duration_seconds": est_duration,
            "sample_rate": 24000,
            "synthetic_audio_id": f"mock_audio_{language}_{word_count}w",
            "cost_class": self.cost_class
        }
