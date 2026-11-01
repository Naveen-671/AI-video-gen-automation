"""End-to-end ResearchAgent orchestrating discovery, extraction, FactLedger, and script proposal."""

import uuid
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timezone

from backend.app.config import DB_PATH
from backend.app.domain.models import (
    ResearchRequest,
    ResearchResponse,
    ScriptProposalModel,
    SceneModel,
    ValidationReportModel
)
from backend.app.research.search_adapters import BaseSearchAdapter, DDGSSearchAdapter
from backend.app.research.extraction_adapters import BaseExtractionAdapter, HTTPTextExtractionAdapter
from backend.app.research.fact_ledger import FactLedgerManager
from backend.app.research.narrative_architect import BaseScriptProposalAdapter, DeterministicScriptProposalAdapter
from backend.app.research.validator import DeterministicScriptValidator
from backend.app.db.repository import save_script_proposal

logger = logging.getLogger("research.agent")


class ResearchAgent:
    """
    Quality-first research agent:
    1. Discovers candidate sources.
    2. Extracts clean document body paragraphs.
    3. Builds FactLedger with source provenance and verified claims.
    4. Constructs archetype-based script proposal with scene beats.
    5. Validates against hallucination, missing evidence, duplicate claims, and cadence.
    """

    def __init__(
        self,
        search_adapter: Optional[BaseSearchAdapter] = None,
        extraction_adapter: Optional[BaseExtractionAdapter] = None,
        proposal_adapter: Optional[BaseScriptProposalAdapter] = None,
        db_path: Path = DB_PATH
    ):
        self.search_adapter = search_adapter or DDGSSearchAdapter()
        self.extraction_adapter = extraction_adapter or HTTPTextExtractionAdapter()
        self.proposal_adapter = proposal_adapter or DeterministicScriptProposalAdapter()
        self.db_path = db_path
        self.ledger = FactLedgerManager(db_path=db_path)

    def run_research(self, req: ResearchRequest) -> ResearchResponse:
        topic = req.topic.strip()
        audience = req.target_audience
        archetype = req.narrative_archetype
        project_id = req.project_id
        max_sources = req.max_sources

        logger.info("Starting research on topic: '%s' (archetype: %s)", topic, archetype)

        # 1. Search for candidate sources
        candidate_sources = self.search_adapter.search(topic, max_results=max_sources)
        if not candidate_sources:
            # Fallback search query
            candidate_sources = self.search_adapter.search(f"{topic} science explanation", max_results=max_sources)

        sources_recorded = []
        all_claims = []

        # 2. Extract content and record in FactLedger
        for cand in candidate_sources:
            extracted_doc = self.extraction_adapter.extract(cand.url)
            # Store source provenance
            src_model = self.ledger.record_source(extracted_doc, project_id=project_id)
            sources_recorded.append(src_model)

            # Derive and record claims bound to source
            claims = self.ledger.extract_claims_from_document(extracted_doc, src_model, project_id=project_id)
            all_claims.extend(claims)

        # If no claims could be extracted, add an explicit UNVERIFIED record
        if not all_claims:
            dummy_claim = self.ledger.record_claim(
                claim_text=f"Preliminary research topic: {topic}",
                quote_excerpt="",
                source=None,
                project_id=project_id,
                override_status="UNVERIFIED",
                uncertainty_rationale="No candidate sources could be extracted for this topic."
            )
            all_claims.append(dummy_claim)

        # 3. Generate structured script proposal
        proposal_dict = self.proposal_adapter.generate_proposal(
            topic=topic,
            target_audience=audience,
            narrative_archetype=archetype,
            claims=all_claims,
            target_duration=16.0
        )

        scenes_raw = proposal_dict["scenes"]

        # 4. Deterministic Validation
        validation = DeterministicScriptValidator.validate(
            scenes=scenes_raw,
            claims=all_claims,
            sources=sources_recorded,
            total_duration=proposal_dict.get("target_duration", 16.0)
        )

        proposal_id = str(uuid.uuid4())
        save_script_proposal(
            proposal_id=proposal_id,
            topic=topic,
            target_audience=audience,
            narrative_archetype=archetype,
            hook_text=proposal_dict["hook_text"],
            scenes=scenes_raw,
            validation=validation.model_dump(),
            project_id=project_id,
            db_path=self.db_path
        )

        scene_models = [
            SceneModel(
                scene_index=s["scene_index"],
                scene_title=s["scene_title"],
                narration_text=s["narration_text"],
                caption_text=s["caption_text"],
                duration_seconds=s["duration_seconds"],
                supporting_claim_ids=s.get("supporting_claim_ids", [])
            )
            for s in scenes_raw
        ]

        proposal_model = ScriptProposalModel(
            id=proposal_id,
            project_id=project_id,
            topic=topic,
            target_audience=audience,
            narrative_archetype=archetype,
            hook_text=proposal_dict["hook_text"],
            scenes=scene_models,
            validation=validation,
            created_at=datetime.now(timezone.utc).isoformat()
        )

        return ResearchResponse(
            project_id=project_id,
            topic=topic,
            target_audience=audience,
            narrative_archetype=archetype,
            sources=sources_recorded,
            claims=all_claims,
            proposal=proposal_model,
            validation=validation
        )
