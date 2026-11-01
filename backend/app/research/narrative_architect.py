"""Narrative architect: archetype-based script proposal generator binding claims to scene beats."""

import uuid
import re
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.app.domain.models import SceneModel, FactClaimModel, ScriptProposalModel, ValidationReportModel

logger = logging.getLogger("research.narrative")

SUPPORTED_ARCHETYPES = {
    "CURIOSITY_GAP": {
        "name": "Curiosity Gap",
        "description": "Mystery Hook → False Assumption → Physical Mechanism → Mind-Bending Payoff",
        "beats": [
            {"title": "The Mystery Hook", "ratio": 0.25, "role": "hook"},
            {"title": "The Complication", "ratio": 0.25, "role": "reveal"},
            {"title": "The Mechanism", "ratio": 0.25, "role": "explanation"},
            {"title": "The Final Payoff", "ratio": 0.25, "role": "payoff"}
        ]
    },
    "HISTORICAL_MICRO_EPIC": {
        "name": "The Historical Micro-Epic",
        "description": "Human Stake → Crisis Point → Decisive Breakthrough → Modern Legacy",
        "beats": [
            {"title": "The Human Stake", "ratio": 0.25, "role": "hook"},
            {"title": "The Crisis", "ratio": 0.25, "role": "conflict"},
            {"title": "The Turning Point", "ratio": 0.25, "role": "resolution"},
            {"title": "The Modern Legacy", "ratio": 0.25, "role": "payoff"}
        ]
    },
    "DISCONFIRMATION_JOURNEY": {
        "name": "The Disconfirmation Journey",
        "description": "Common Myth → Critical Counter-Evidence → Physical Reality → Essential Takeaway",
        "beats": [
            {"title": "The Common Myth", "ratio": 0.25, "role": "hook"},
            {"title": "The Counter-Evidence", "ratio": 0.25, "role": "evidence"},
            {"title": "The Physical Reality", "ratio": 0.25, "role": "explanation"},
            {"title": "The Paradigm Shift", "ratio": 0.25, "role": "payoff"}
        ]
    },
    "SCALE_SHOCK": {
        "name": "The Scale Shock",
        "description": "Familiar Anchor → Exponential Leap → Cosmic Perspective → Grounding Truth",
        "beats": [
            {"title": "The Familiar Anchor", "ratio": 0.25, "role": "hook"},
            {"title": "The First Leap", "ratio": 0.25, "role": "escalation"},
            {"title": "The Cosmic Perspective", "ratio": 0.25, "role": "extreme"},
            {"title": "The Grounding Truth", "ratio": 0.25, "role": "payoff"}
        ]
    }
}


class BaseScriptProposalAdapter(ABC):
    @abstractmethod
    def generate_proposal(
        self,
        topic: str,
        target_audience: str,
        narrative_archetype: str,
        claims: List[FactClaimModel],
        target_duration: float = 16.0
    ) -> Dict[str, Any]:
        """Generates a structured script proposal with beats and claim bindings."""
        pass


class DeterministicScriptProposalAdapter(BaseScriptProposalAdapter):
    """
    Deterministic script proposal generator constructing structured, spoken-ear Short scripts
    directly from verified FactLedger claims and narrative archetypes.
    Adheres strictly to the zero-recurring-cost policy and ensures claim-to-beat traceability.
    """

    def generate_proposal(
        self,
        topic: str,
        target_audience: str,
        narrative_archetype: str,
        claims: List[FactClaimModel],
        target_duration: float = 16.0
    ) -> Dict[str, Any]:
        archetype_key = narrative_archetype.upper() if narrative_archetype else "CURIOSITY_GAP"
        if archetype_key not in SUPPORTED_ARCHETYPES:
            archetype_key = "CURIOSITY_GAP"

        archetype_info = SUPPORTED_ARCHETYPES[archetype_key]
        beat_defs = archetype_info["beats"]

        # Filter verified claims for binding
        verified_claims = [c for c in claims if c.evidence_status == "VERIFIED"]
        all_claims = claims if claims else []

        # Target 2.4 words per second
        total_target_words = int(target_duration * 2.4)
        words_per_beat = max(8, total_target_words // len(beat_defs))
        beat_duration = round(target_duration / len(beat_defs), 1)

        scenes: List[Dict[str, Any]] = []

        for idx, beat in enumerate(beat_defs):
            # Select supporting claims for this beat
            assigned_claims: List[str] = []
            if verified_claims:
                assigned_c = verified_claims[idx % len(verified_claims)]
                assigned_claims.append(assigned_c.id)
            elif all_claims:
                assigned_claims.append(all_claims[idx % len(all_claims)].id)

            role = beat["role"]
            if role == "hook":
                if archetype_key == "CURIOSITY_GAP":
                    narration = f"You think you understand {topic}, but reality is far stranger."
                    caption = f"The Truth About {topic[:25]}"
                elif archetype_key == "HISTORICAL_MICRO_EPIC":
                    narration = f"In the story of {topic}, one single moment changed everything."
                    caption = f"The Crisis of {topic[:25]}"
                elif archetype_key == "DISCONFIRMATION_JOURNEY":
                    narration = f"Almost everything you have heard about {topic} is mistaken."
                    caption = f"The Big Myth: {topic[:25]}"
                else:
                    narration = f"Start with something ordinary to understand the sheer scale of {topic}."
                    caption = f"Measuring {topic[:25]}"

            elif role in ("reveal", "conflict", "evidence", "escalation"):
                if assigned_claims and verified_claims:
                    lead_claim = next((c for c in verified_claims if c.id in assigned_claims), None)
                    claim_sentence = lead_claim.claim_text if lead_claim else topic
                    # Truncate if overly long
                    claim_words = claim_sentence.split()
                    if len(claim_words) > 14:
                        claim_sentence = " ".join(claim_words[:14]) + "."
                    narration = f"Scientific evidence reveals: {claim_sentence}"
                    caption = "What Evidence Proves"
                else:
                    narration = f"When we examine {topic} closely, the established assumptions break down."
                    caption = "The Direct Evidence"

            elif role == "explanation":
                if assigned_claims and verified_claims:
                    lead_claim = next((c for c in verified_claims if c.id in assigned_claims), None)
                    narration = f"This occurs because {lead_claim.claim_text if lead_claim else topic}."
                    caption = "How It Actually Works"
                else:
                    narration = f"The underlying mechanism proves that {topic} operates on precise physical laws."
                    caption = "Under The Hood"

            else:  # payoff / resolution
                narration = f"That is why {topic} shapes our understanding of the universe today."
                caption = "The Real Takeaway"

            scenes.append({
                "scene_index": idx,
                "scene_title": beat["title"],
                "narration_text": narration,
                "caption_text": caption,
                "duration_seconds": beat_duration,
                "supporting_claim_ids": assigned_claims,
                "visual_directive": f"Cinematic visual supporting {beat['title'].lower()}"
            })

        hook_text = scenes[0]["narration_text"] if scenes else f"The truth behind {topic}."

        return {
            "topic": topic,
            "target_audience": target_audience,
            "narrative_archetype": archetype_key,
            "hook_text": hook_text,
            "scenes": scenes,
            "words_count": sum(len(s["narration_text"].split()) for s in scenes),
            "target_duration": target_duration
        }
