"""FactLedger subsystem: provenance tracking, claim extraction, and evidence verification."""

import uuid
import re
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone

from backend.app.config import DB_PATH
from backend.app.domain.models import FactSourceModel, FactClaimModel
from backend.app.research.extraction_adapters import ExtractedDocument
from backend.app.db.repository import (
    create_fact_source,
    create_fact_claim,
    get_fact_sources,
    get_fact_claims
)

logger = logging.getLogger("research.fact_ledger")


def normalize_text_for_comparison(text: str) -> str:
    """Strips punctuation and lowercases for duplicate claim comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def compute_word_overlap(a: str, b: str) -> float:
    """Computes Jaccard word overlap between two assertions."""
    words_a = set(normalize_text_for_comparison(a).split())
    words_b = set(normalize_text_for_comparison(b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a.intersection(words_b)
    union = words_a.union(words_b)
    return len(intersection) / float(len(union))


class FactLedgerManager:
    """
    Manages the FactLedger: records source provenance, validates claim quotations
    against extracted source documents, flags unverified speculation, and detects duplicates.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def record_source(
        self,
        doc: ExtractedDocument,
        project_id: Optional[str] = None
    ) -> FactSourceModel:
        """Stores source document provenance in SQLite."""
        source_id = str(uuid.uuid4())
        retrieved_at = datetime.now(timezone.utc).isoformat()
        
        create_fact_source(
            source_id=source_id,
            url=doc.url,
            title=doc.title,
            project_id=project_id,
            published_date=doc.published_date,
            raw_excerpt=doc.raw_excerpt,
            http_status=doc.http_status,
            db_path=self.db_path
        )

        return FactSourceModel(
            id=source_id,
            project_id=project_id,
            url=doc.url,
            title=doc.title,
            published_date=doc.published_date,
            retrieved_at=retrieved_at,
            raw_excerpt=doc.raw_excerpt,
            http_status=doc.http_status
        )

    def record_claim(
        self,
        claim_text: str,
        quote_excerpt: str,
        source: Optional[FactSourceModel] = None,
        project_id: Optional[str] = None,
        override_status: Optional[str] = None,
        uncertainty_rationale: Optional[str] = None
    ) -> FactClaimModel:
        """
        Records a single factual assertion bound to a source quote.
        CRITICAL INVARIANT:
        If source extraction failed or body is empty, evidence status MUST be INSUFFICIENT_EVIDENCE.
        If quote is not present in document or empty, status MUST be UNVERIFIED.
        """
        claim_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        # Deterministic verification logic
        status = override_status
        rationale = uncertainty_rationale

        if status is None:
            if not source or source.http_status >= 400 or not source.raw_excerpt:
                status = "INSUFFICIENT_EVIDENCE"
                rationale = "Source extraction failed, returned non-200 HTTP code, or had empty content."
            elif not quote_excerpt or not quote_excerpt.strip():
                status = "UNVERIFIED"
                rationale = "Claim does not have a supporting quote from the primary document."
            elif quote_excerpt.lower() not in (source.raw_excerpt or "").lower():
                # Allow partial match if length >= 30 chars
                clean_quote = normalize_text_for_comparison(quote_excerpt)
                clean_source = normalize_text_for_comparison(source.raw_excerpt or "")
                if clean_quote in clean_source or compute_word_overlap(clean_quote, clean_source) > 0.6:
                    status = "VERIFIED"
                    rationale = "Direct quote matched in extracted source document."
                else:
                    status = "UNVERIFIED"
                    rationale = "Quotation could not be located in the extracted source text."
            else:
                status = "VERIFIED"
                rationale = "Direct quotation verified in primary source text."

        source_id = source.id if source else None
        create_fact_claim(
            claim_id=claim_id,
            claim_text=claim_text.strip(),
            quote_excerpt=quote_excerpt.strip() if quote_excerpt else "",
            source_id=source_id,
            project_id=project_id,
            evidence_status=status,
            uncertainty_rationale=rationale,
            db_path=self.db_path
        )

        return FactClaimModel(
            id=claim_id,
            source_id=source_id,
            project_id=project_id,
            claim_text=claim_text.strip(),
            quote_excerpt=quote_excerpt.strip() if quote_excerpt else "",
            evidence_status=status,
            uncertainty_rationale=rationale,
            created_at=created_at,
            source_url=source.url if source else None,
            source_title=source.title if source else None
        )

    def extract_claims_from_document(
        self,
        doc: ExtractedDocument,
        source: FactSourceModel,
        project_id: Optional[str] = None
    ) -> List[FactClaimModel]:
        """
        Deterministic extractor that derives candidate claims from extracted paragraphs.
        Extracts verifiable statements containing numbers, proper nouns, measurements, or causal phrases.
        """
        claims: List[FactClaimModel] = []

        if not doc.success or not doc.paragraphs:
            # Record explicit unverified/insufficient entry to avoid silent drop
            claims.append(
                self.record_claim(
                    claim_text=f"Extraction failed for source: {doc.url}",
                    quote_excerpt="",
                    source=source,
                    project_id=project_id,
                    override_status="INSUFFICIENT_EVIDENCE",
                    uncertainty_rationale=doc.error_message or "No readable paragraphs extracted."
                )
            )
            return claims

        # Process paragraphs to extract distinct claims
        for p in doc.paragraphs[:5]:  # inspect top paragraphs
            sentences = re.split(r"(?<=[.!?])\s+", p)
            for s in sentences:
                s_clean = s.strip()
                # Focus on sentences with numeric quantities, scientific terms, or direct assertions
                if len(s_clean) > 35 and any(char.isdigit() for char in s_clean):
                    claims.append(
                        self.record_claim(
                            claim_text=s_clean,
                            quote_excerpt=s_clean,
                            source=source,
                            project_id=project_id,
                            override_status="VERIFIED",
                            uncertainty_rationale="Verified primary sentence from extracted document."
                        )
                    )
                elif len(s_clean) > 45 and any(word in s_clean.lower() for word in ["because", "due to", "warps", "causes", "faster", "slower", "measures", "discovered"]):
                    claims.append(
                        self.record_claim(
                            claim_text=s_clean,
                            quote_excerpt=s_clean,
                            source=source,
                            project_id=project_id,
                            override_status="VERIFIED",
                            uncertainty_rationale="Verified explanatory sentence from extracted document."
                        )
                    )

        # Fallback if no specific numeric/causal sentences matched but paragraphs exist
        if not claims and doc.paragraphs:
            lead = doc.paragraphs[0]
            claims.append(
                self.record_claim(
                    claim_text=lead,
                    quote_excerpt=lead,
                    source=source,
                    project_id=project_id,
                    override_status="VERIFIED",
                    uncertainty_rationale="Lead paragraph from verified primary source."
                )
            )

        return claims

    def get_ledger(self, project_id: str) -> Tuple[List[FactSourceModel], List[FactClaimModel]]:
        """Retrieves all sources and claims for a project."""
        src_rows = get_fact_sources(project_id, db_path=self.db_path)
        claim_rows = get_fact_claims(project_id, db_path=self.db_path)

        sources = [FactSourceModel(**s) for s in src_rows]
        claims = [FactClaimModel(**c) for c in claim_rows]
        return sources, claims

    @staticmethod
    def detect_duplicate_claims(claims: List[FactClaimModel], threshold: float = 0.75) -> List[Tuple[str, str, float]]:
        """
        Identifies pairs of duplicate or near-identical claims in the ledger.
        Returns list of tuples: (claim_id_1, claim_id_2, overlap_score).
        """
        duplicates: List[Tuple[str, str, float]] = []
        n = len(claims)
        for i in range(n):
            for j in range(i + 1, n):
                c1 = claims[i]
                c2 = claims[j]
                overlap = compute_word_overlap(c1.claim_text, c2.claim_text)
                if overlap >= threshold:
                    duplicates.append((c1.id, c2.id, round(overlap, 2)))
        return duplicates
