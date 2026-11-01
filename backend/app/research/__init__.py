"""Research Agent and FactLedger package."""

from backend.app.research.search_adapters import (
    BaseSearchAdapter,
    DDGSSearchAdapter,
    MockSearchAdapter,
    CandidateSource
)
from backend.app.research.extraction_adapters import (
    BaseExtractionAdapter,
    HTTPTextExtractionAdapter,
    MockExtractionAdapter,
    ExtractedDocument
)
from backend.app.research.fact_ledger import FactLedgerManager
from backend.app.research.narrative_architect import (
    BaseScriptProposalAdapter,
    DeterministicScriptProposalAdapter,
    SUPPORTED_ARCHETYPES
)
from backend.app.research.validator import DeterministicScriptValidator
from backend.app.research.agent import ResearchAgent

__all__ = [
    "BaseSearchAdapter",
    "DDGSSearchAdapter",
    "MockSearchAdapter",
    "CandidateSource",
    "BaseExtractionAdapter",
    "HTTPTextExtractionAdapter",
    "MockExtractionAdapter",
    "ExtractedDocument",
    "FactLedgerManager",
    "BaseScriptProposalAdapter",
    "DeterministicScriptProposalAdapter",
    "SUPPORTED_ARCHETYPES",
    "DeterministicScriptValidator",
    "ResearchAgent",
]
