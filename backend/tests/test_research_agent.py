"""Unit and integration tests for Stage 2: Quality Research Agent & FactLedger Intelligence."""

import uuid
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.api.main import app
from backend.app.db.connection import init_db, get_connection
from backend.app.domain.models import (
    ResearchRequest,
    FactSourceModel,
    FactClaimModel
)
from backend.app.research.search_adapters import (
    DDGSSearchAdapter,
    MockSearchAdapter,
    CandidateSource
)
from backend.app.research.extraction_adapters import (
    HTTPTextExtractionAdapter,
    MockExtractionAdapter,
    ExtractedDocument
)
from backend.app.research.fact_ledger import FactLedgerManager, compute_word_overlap
from backend.app.research.narrative_architect import (
    DeterministicScriptProposalAdapter,
    SUPPORTED_ARCHETYPES
)
from backend.app.research.validator import DeterministicScriptValidator
from backend.app.research.agent import ResearchAgent
from backend.app.worker.runner import WorkerRunner
from backend.app.db.repository import create_project, get_project

client = TestClient(app)


@pytest.fixture
def test_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_research.db"
    init_db(db_file)
    monkeypatch.setattr("backend.app.api.main.DB_PATH", db_file)
    monkeypatch.setattr("backend.app.db.repository.DB_PATH", db_file)
    return db_file


def test_search_adapters_return_candidate_sources():
    """Search adapters return candidate sources with title, URL, and snippet."""
    mock_search = MockSearchAdapter()
    candidates = mock_search.search("gravitational time dilation", max_results=3)
    assert len(candidates) >= 2
    for cand in candidates:
        assert cand.url.startswith("http")
        assert len(cand.title) > 0
        assert len(cand.snippet) > 0


def test_search_snippet_never_accepted_as_verified_evidence(test_db: Path):
    """
    Search snippets cannot be presented as verified evidence.
    If full document extraction fails (e.g. 404 or network timeout), claim MUST be marked
    INSUFFICIENT_EVIDENCE or UNVERIFIED with explicit rationale, never silently VERIFIED.
    """
    ledger = FactLedgerManager(db_path=test_db)
    
    # Simulate a failed document extraction
    failed_doc = ExtractedDocument(
        url="https://example.com/dead_link",
        title="404 Not Found",
        http_status=404,
        success=False,
        error_message="HTTP 404 Not Found"
    )
    src_model = ledger.record_source(failed_doc)
    
    # Attempting to derive claims from failed extraction must yield INSUFFICIENT_EVIDENCE
    claims = ledger.extract_claims_from_document(failed_doc, src_model)
    assert len(claims) >= 1
    assert claims[0].evidence_status == "INSUFFICIENT_EVIDENCE"
    assert "failed" in claims[0].uncertainty_rationale.lower() or "404" in claims[0].uncertainty_rationale.lower()


def test_fact_ledger_provenance_and_verification(test_db: Path):
    """
    FactLedger records source URL, retrieval time, published date, raw excerpt,
    and binds verified claims with direct quote matching.
    """
    ledger = FactLedgerManager(db_path=test_db)
    mock_extract = MockExtractionAdapter()
    doc = mock_extract.extract("https://www.nist.gov/atomic-clocks/putting-einstein-test")

    src = ledger.record_source(doc)
    assert src.url == doc.url
    assert src.title == doc.title
    assert src.published_date == "2022-02-16"
    assert src.http_status == 200

    claims = ledger.extract_claims_from_document(doc, src)
    assert len(claims) >= 1
    verified_claims = [c for c in claims if c.evidence_status == "VERIFIED"]
    assert len(verified_claims) >= 1
    assert "optical lattice clocks" in verified_claims[0].quote_excerpt or "gravitational" in verified_claims[0].quote_excerpt.lower()


def test_unsupported_claim_marked_unverified(test_db: Path):
    """A claim lacking quotation or not present in source excerpt is marked UNVERIFIED."""
    ledger = FactLedgerManager(db_path=test_db)
    src = ledger.record_source(
        ExtractedDocument(
            url="https://example.com/source",
            title="General Physics",
            raw_excerpt="Atoms consist of protons, neutrons, and electrons."
        )
    )

    # Claim asserts something completely unrelated to the excerpt
    claim = ledger.record_claim(
        claim_text="Aliens built the pyramids in 2500 BC.",
        quote_excerpt="Aliens built the pyramids",
        source=src
    )
    assert claim.evidence_status == "UNVERIFIED"
    assert "could not be located" in claim.uncertainty_rationale.lower()


def test_duplicate_claim_detection(test_db: Path):
    """Duplicate claim detector identifies claims with high lexical overlap."""
    c1 = FactClaimModel(
        id="c1",
        claim_text="Clocks at sea level tick slower than clocks on Mount Everest by thirty microseconds per year.",
        quote_excerpt="Clocks at sea level tick slower",
        created_at="2026-10-20T00:00:00"
    )
    c2 = FactClaimModel(
        id="c2",
        claim_text="Clocks on Mount Everest tick faster than clocks at sea level by 30 microseconds annually.",
        quote_excerpt="Clocks on Mount Everest tick faster",
        created_at="2026-10-20T00:00:00"
    )
    c3 = FactClaimModel(
        id="c3",
        claim_text="Quantum computers utilize superposition and entanglement for Shor factoring.",
        quote_excerpt="Quantum computers utilize superposition",
        created_at="2026-10-20T00:00:00"
    )

    duplicates = FactLedgerManager.detect_duplicate_claims([c1, c2, c3], threshold=0.55)
    assert len(duplicates) == 1
    assert duplicates[0][0] == "c1"
    assert duplicates[0][1] == "c2"


def test_all_narrative_archetypes_generate_valid_beats():
    """Verifies that all 4 narrative archetypes produce structured beats with claim references."""
    adapter = DeterministicScriptProposalAdapter()
    dummy_claim = FactClaimModel(
        id="fact_test_1",
        claim_text="Earth's mass warps spacetime, slowing time near its surface.",
        quote_excerpt="Earth's mass warps spacetime",
        evidence_status="VERIFIED",
        created_at="2026-10-20T00:00:00"
    )

    for arch_key in SUPPORTED_ARCHETYPES.keys():
        proposal = adapter.generate_proposal(
            topic="Gravitational Time Dilation",
            target_audience="Curious Adults",
            narrative_archetype=arch_key,
            claims=[dummy_claim],
            target_duration=16.0
        )
        assert proposal["narrative_archetype"] == arch_key
        assert len(proposal["scenes"]) == 4
        assert proposal["words_count"] > 25
        # Verify first beat has a hook
        assert len(proposal["hook_text"]) > 10
        # Verify scene beats bind supporting claim
        bound_claims = [cid for s in proposal["scenes"] for cid in s["supporting_claim_ids"]]
        assert "fact_test_1" in bound_claims


def test_validation_flags_invalid_claim_reference():
    """Validator raises ERROR when a scene cites a non-existent claim ID."""
    validator = DeterministicScriptValidator()
    scenes = [
        {
            "scene_index": 0,
            "scene_title": "The Hook",
            "narration_text": "Did you know that clocks tick differently?",
            "duration_seconds": 4.0,
            "supporting_claim_ids": ["nonexistent_claim_id_999"]
        }
    ]
    claims = [
        FactClaimModel(
            id="real_claim_1",
            claim_text="Real assertion.",
            quote_excerpt="Real assertion.",
            evidence_status="VERIFIED",
            created_at="2026-10-20T00:00:00"
        )
    ]
    sources = [
        FactSourceModel(
            id="src_1",
            url="https://example.com",
            title="Example",
            retrieved_at="2026-10-20T00:00:00"
        )
    ]

    report = validator.validate(scenes=scenes, claims=claims, sources=sources, total_duration=4.0)
    assert report.passed is False
    assert any(err.rule == "INVALID_CLAIM_REFERENCE" for err in report.errors)


def test_validation_flags_unsupported_claim_in_narration():
    """Validator raises WARNING when a scene references an unverified claim."""
    validator = DeterministicScriptValidator()
    scenes = [
        {
            "scene_index": 0,
            "scene_title": "The Hook",
            "narration_text": "Did you know that speculative things happen?",
            "duration_seconds": 4.0,
            "supporting_claim_ids": ["unverified_claim_1"]
        }
    ]
    claims = [
        FactClaimModel(
            id="unverified_claim_1",
            claim_text="Unproven speculation.",
            quote_excerpt="",
            evidence_status="UNVERIFIED",
            uncertainty_rationale="No source quote available.",
            created_at="2026-10-20T00:00:00"
        )
    ]
    sources = [
        FactSourceModel(
            id="src_1",
            url="https://example.com",
            title="Example",
            retrieved_at="2026-10-20T00:00:00"
        )
    ]

    report = validator.validate(scenes=scenes, claims=claims, sources=sources, total_duration=4.0)
    assert any(w.rule == "UNSUPPORTED_CLAIM_IN_SCRIPT" for w in report.warnings)


def test_end_to_end_research_agent_workflow(test_db: Path):
    """Tests the complete research workflow from discovery to FactLedger and proposal generation."""
    agent = ResearchAgent(
        search_adapter=MockSearchAdapter(),
        extraction_adapter=MockExtractionAdapter(),
        db_path=test_db
    )

    req = ResearchRequest(
        topic="Gravitational Time Dilation",
        target_audience="General",
        narrative_archetype="CURIOSITY_GAP",
        max_sources=2
    )

    res = agent.run_research(req)

    assert res.topic == "Gravitational Time Dilation"
    assert len(res.sources) >= 1
    assert len(res.claims) >= 1
    assert res.proposal is not None
    assert len(res.proposal.scenes) == 4
    assert res.validation is not None
    # Check that errors is 0 (valid references)
    assert len(res.validation.errors) == 0


def test_worker_research_topic_job(test_db: Path):
    """Verifies that WorkerRunner leases and executes RESEARCH_TOPIC stage jobs."""
    worker = WorkerRunner(db_path=test_db)
    payload = {
        "topic": "Neutron Stars",
        "target_audience": "Science Enthusiasts",
        "narrative_archetype": "SCALE_SHOCK",
        "max_sources": 2
    }
    result = worker.process_job_stage("RESEARCH_TOPIC", payload)
    assert result["status"] == "SUCCESS"
    assert "research" in result
    research_data = result["research"]
    assert research_data["topic"] == "Neutron Stars"
    assert len(research_data["proposal"]["scenes"]) == 4


def test_api_research_endpoints(test_db: Path):
    """Verifies FastAPI /research/discover and /projects/{id}/facts endpoints."""
    # 1. Discover research
    res = client.post(
        "/research/discover",
        json={
            "topic": "Quantum Computing",
            "target_audience": "Tech Enthusiasts",
            "narrative_archetype": "CURIOSITY_GAP",
            "max_sources": 2
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["topic"] == "Quantum Computing"
    assert "sources" in data
    assert "claims" in data
    assert "proposal" in data

    # 2. Test project fact retrieval
    proj_id = create_project(topic="Project for facts test", db_path=test_db)
    fact_res = client.get(f"/projects/{proj_id}/facts")
    assert fact_res.status_code == 200
    fact_data = fact_res.json()
    assert "sources" in fact_data
    assert "claims" in fact_data
