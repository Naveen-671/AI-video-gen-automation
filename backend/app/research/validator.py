"""Deterministic script and fact validation rules."""

import re
import logging
from typing import List, Dict, Any, Set, Tuple
from backend.app.domain.models import (
    FactSourceModel,
    FactClaimModel,
    SceneModel,
    ValidationWarningModel,
    ValidationReportModel
)
from backend.app.research.fact_ledger import FactLedgerManager

logger = logging.getLogger("research.validator")


class DeterministicScriptValidator:
    """
    Executes rule-based editorial and factual validation on script proposals.
    Flags missing sources, unsupported claims, duplicate claims, invalid claim references,
    and pacing violations.
    """

    @staticmethod
    def validate(
        scenes: List[Dict[str, Any]],
        claims: List[FactClaimModel],
        sources: List[FactSourceModel],
        total_duration: float = 16.0
    ) -> ValidationReportModel:
        errors: List[ValidationWarningModel] = []
        warnings: List[ValidationWarningModel] = []

        source_map = {s.id: s for s in sources}
        claim_map = {c.id: c for c in claims}

        # 1. Check Missing Sources for Claims
        for claim in claims:
            if claim.source_id and claim.source_id not in source_map:
                errors.append(
                    ValidationWarningModel(
                        rule="MISSING_SOURCE",
                        severity="ERROR",
                        message=f"Claim '{claim.id}' references source '{claim.source_id}' which does not exist in FactLedger.",
                        entity_id=claim.id
                    )
                )
            elif claim.source_id and claim.source_id in source_map:
                src = source_map[claim.source_id]
                if src.http_status >= 400 or not src.raw_excerpt:
                    warnings.append(
                        ValidationWarningModel(
                            rule="SOURCE_EXTRACTION_FAILURE",
                            severity="WARNING",
                            message=f"Claim '{claim.id}' is linked to source '{src.url}' which failed retrieval (HTTP {src.http_status}).",
                            entity_id=claim.id
                        )
                    )

        # 2. Check Invalid Claim References in Scene Beats
        referenced_claim_ids: Set[str] = set()
        for idx, scene in enumerate(scenes):
            ref_ids = scene.get("supporting_claim_ids", [])
            for cid in ref_ids:
                referenced_claim_ids.add(cid)
                if cid not in claim_map:
                    errors.append(
                        ValidationWarningModel(
                            rule="INVALID_CLAIM_REFERENCE",
                            severity="ERROR",
                            message=f"Scene {idx} ('{scene.get('scene_title')}') references non-existent claim ID '{cid}'.",
                            entity_id=cid
                        )
                    )
                else:
                    # 3. Check Unsupported Claims referenced in active narration
                    clm = claim_map[cid]
                    if clm.evidence_status in ("UNVERIFIED", "INSUFFICIENT_EVIDENCE"):
                        warnings.append(
                            ValidationWarningModel(
                                rule="UNSUPPORTED_CLAIM_IN_SCRIPT",
                                severity="WARNING",
                                message=f"Scene {idx} references claim '{cid}' which has evidence status '{clm.evidence_status}': {clm.uncertainty_rationale}",
                                entity_id=cid
                            )
                        )

        # 4. Check Duplicate Claims in FactLedger
        duplicates = FactLedgerManager.detect_duplicate_claims(claims, threshold=0.75)
        for c1, c2, score in duplicates:
            warnings.append(
                ValidationWarningModel(
                    rule="DUPLICATE_CLAIM",
                    severity="WARNING",
                    message=f"Claims '{c1}' and '{c2}' have {int(score * 100)}% lexical overlap.",
                    entity_id=c1
                )
            )

        # 5. Pacing & Lexical Density
        total_words = 0
        total_dur = 0.0
        for idx, scene in enumerate(scenes):
            text = scene.get("narration_text", "")
            words = text.split()
            word_count = len(words)
            total_words += word_count
            dur = float(scene.get("duration_seconds", 5.0))
            total_dur += dur

            # Check sentence length for speech cadence
            sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
            for s in sentences:
                if len(s.split()) > 16:
                    warnings.append(
                        ValidationWarningModel(
                            rule="SENTENCE_TOO_LONG_FOR_SPEECH",
                            severity="WARNING",
                            message=f"Scene {idx} has a sentence with {len(s.split())} words (> 16 words). May strain neural TTS naturalness.",
                            entity_id=str(idx)
                        )
                    )

        wps = round(total_words / total_dur, 2) if total_dur > 0 else 0.0
        if wps < 2.0 or wps > 3.0:
            warnings.append(
                ValidationWarningModel(
                    rule="CADENCE_OUT_OF_BOUNDS",
                    severity="WARNING",
                    message=f"Overall spoken rate is {wps} words/sec. Ideal target is 2.2 to 2.8 WPS for short-form retention.",
                    entity_id="script"
                )
            )

        # 6. Hook Potency Check (Opening 0-3s)
        if scenes:
            hook_text = scenes[0].get("narration_text", "").lower()
            curiosity_markers = ["?", "you", "think", "secret", "never", "actually", "why", "how", "what", "mistaken", "ordinary", "truth"]
            if not any(marker in hook_text for marker in curiosity_markers):
                warnings.append(
                    ValidationWarningModel(
                        rule="WEAK_HOOK",
                        severity="WARNING",
                        message="Opening beat lacks a curiosity question or contrast word to stop viewer scrolling.",
                        entity_id="scene_0"
                    )
                )

        # 7. Coverage Ratio: What fraction of scenes have verified claim bindings?
        scenes_with_verified = 0
        for s in scenes:
            ref_ids = s.get("supporting_claim_ids", [])
            has_verified = any(claim_map.get(cid) and claim_map[cid].evidence_status == "VERIFIED" for cid in ref_ids)
            if has_verified:
                scenes_with_verified += 1
        coverage = round(scenes_with_verified / float(len(scenes)), 2) if scenes else 0.0

        passed = len(errors) == 0

        return ValidationReportModel(
            passed=passed,
            errors=errors,
            warnings=warnings,
            lexical_density_wps=wps,
            total_spoken_words=total_words,
            total_duration_sec=round(total_dur, 1),
            claim_coverage_ratio=coverage
        )
