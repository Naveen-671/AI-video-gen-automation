"""Editorial QA evaluator assessing narrative hook, visual relevance, pacing, and retention quality."""

import re
import uuid
import logging
from typing import Dict, Any, List

logger = logging.getLogger("editorial_qa")

HOOK_KEYWORDS = {
    "why", "how", "what", "ever", "wonder", "secret", "never", "faster", "slower",
    "gravity", "stop", "think", "hidden", "truth", "discover", "proof", "believe",
    "shocking", "earth", "time", "space", "feet", "head", "clock"
}

PAYOFF_KEYWORDS = {
    "remember", "next time", "so", "means", "every second", "now you know",
    "lifetime", "universe", "reality", "fact", "world", "takeaway", "lesson"
}

class EditorialQA:
    """Evaluates narrative engagement, visual relevance, and editorial pacing."""

    @classmethod
    def evaluate(
        cls,
        project: Dict[str, Any],
        scenes: List[Dict[str, Any]],
        asset_provenances: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        warnings: List[Dict[str, Any]] = []
        score = 100

        # 1. Hook Evaluation (Scene 0)
        hook_eval = cls._evaluate_hook(scenes)
        score -= (100 - hook_eval["score"]) * 0.35
        for w in hook_eval["warnings"]:
            warnings.append(w)

        # 2. Pacing Evaluation
        pacing_eval = cls._evaluate_pacing(scenes)
        score -= (100 - pacing_eval["score"]) * 0.25
        for w in pacing_eval["warnings"]:
            warnings.append(w)

        # 3. Visual Relevance & Diversity
        relevance_eval = cls._evaluate_visuals(scenes, asset_provenances)
        score -= (100 - relevance_eval["score"]) * 0.25
        for w in relevance_eval["warnings"]:
            warnings.append(w)

        # 4. Audio & Payoff Evaluation
        audio_eval = cls._evaluate_audio_and_payoff(project, scenes)
        score -= (100 - audio_eval["score"]) * 0.15
        for w in audio_eval["warnings"]:
            warnings.append(w)

        final_score = max(10, min(100, int(round(score))))
        overall_status = "PASSED" if final_score >= 80 else ("WARNING" if final_score >= 60 else "FAILED")

        return {
            "review_id": str(uuid.uuid4()),
            "overall_status": overall_status,
            "score": final_score,
            "hook_evaluation": hook_eval,
            "pacing_evaluation": pacing_eval,
            "relevance_evaluation": relevance_eval,
            "audio_evaluation": audio_eval,
            "warnings": warnings
        }

    @classmethod
    def _evaluate_hook(cls, scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
        warnings = []
        score = 100

        if not scenes:
            return {"score": 20, "hook_present": False, "warnings": [{"category": "HOOK", "severity": "WARNING", "message": "No scenes present in project."}]}

        first_scene = scenes[0]
        text = (first_scene.get("narration_text") or first_scene.get("caption_text") or "").strip()
        words = text.split()
        word_count = len(words)

        if word_count == 0:
            return {"score": 10, "hook_present": False, "warnings": [{"category": "HOOK", "severity": "WARNING", "message": "Opening scene has empty narration."}]}

        # Check for hook keywords
        lower_text = text.lower()
        has_hook_keyword = any(kw in lower_text for kw in HOOK_KEYWORDS)
        has_question_or_punch = "?" in text or "!" in text

        if not has_hook_keyword and not has_question_or_punch:
            score -= 30
            warnings.append({
                "category": "HOOK",
                "severity": "WARNING",
                "message": "Opening beat lacks an immediate curiosity hook or tension question."
            })

        if word_count > 25:
            score -= 20
            warnings.append({
                "category": "HOOK",
                "severity": "SUGGESTION",
                "message": f"Opening scene is wordy ({word_count} words). Aim for a punchy opening under 18 words."
            })

        duration = float(first_scene.get("duration_seconds", 5.0))
        if duration > 7.0:
            score -= 15
            warnings.append({
                "category": "HOOK",
                "severity": "SUGGESTION",
                "message": f"Opening scene duration ({duration:.1f}s) may cause early viewer drop-off before first visual cut."
            })

        return {
            "score": max(10, score),
            "hook_present": has_hook_keyword or has_question_or_punch,
            "word_count": word_count,
            "warnings": warnings
        }

    @classmethod
    def _evaluate_pacing(cls, scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
        warnings = []
        score = 100

        for i, s in enumerate(scenes):
            dur = float(s.get("duration_seconds", 5.0))
            text = s.get("narration_text", "")
            words = len(text.split())
            wps = words / dur if dur > 0 else 0

            if wps > 3.3:
                score -= 10
                warnings.append({
                    "category": "PACING",
                    "severity": "WARNING",
                    "message": f"Scene {i + 1} has rushed speech ({wps:.1f} words/sec; target 2.2-2.8).",
                    "scene_index": i
                })
            elif wps < 1.4 and words > 0:
                score -= 5
                warnings.append({
                    "category": "PACING",
                    "severity": "SUGGESTION",
                    "message": f"Scene {i + 1} has sluggish pacing ({wps:.1f} words/sec).",
                    "scene_index": i
                })

            if dur > 8.5:
                score -= 10
                warnings.append({
                    "category": "PACING",
                    "severity": "WARNING",
                    "message": f"Scene {i + 1} is static for {dur:.1f}s. Vertical videos retain better with cuts under 6s.",
                    "scene_index": i
                })

        return {
            "score": max(20, score),
            "warnings": warnings
        }

    @classmethod
    def _evaluate_visuals(cls, scenes: List[Dict[str, Any]], asset_provenances: List[Dict[str, Any]]) -> Dict[str, Any]:
        warnings = []
        score = 100

        visual_paths = [s.get("visual_asset_path") for s in scenes if s.get("visual_asset_path")]
        unique_visuals = set(visual_paths)

        if len(scenes) > 1 and len(unique_visuals) < len(scenes):
            repeated_count = len(scenes) - len(unique_visuals)
            score -= (repeated_count * 15)
            warnings.append({
                "category": "RELEVANCE",
                "severity": "WARNING",
                "message": f"{repeated_count} scene(s) share identical visual backgrounds. Use distinct visuals for each beat."
            })

        # Check motion presets
        motion_presets = [s.get("motion_preset", "zoom_in") for s in scenes]
        if all(m == "static" for m in motion_presets) and len(scenes) > 1:
            score -= 20
            warnings.append({
                "category": "RETENTION",
                "severity": "WARNING",
                "message": "All scenes have static motion. Add Ken Burns pan/zoom to boost retention."
            })

        # Check claim linkage
        unlinked_scenes = [i for i, s in enumerate(scenes) if not s.get("supporting_claim_ids")]
        if unlinked_scenes:
            score -= len(unlinked_scenes) * 5
            warnings.append({
                "category": "RELEVANCE",
                "severity": "SUGGESTION",
                "message": f"{len(unlinked_scenes)} scene(s) are not explicitly linked to FactLedger claim IDs."
            })

        return {
            "score": max(20, score),
            "unique_visuals_count": len(unique_visuals),
            "total_scenes": len(scenes),
            "warnings": warnings
        }

    @classmethod
    def _evaluate_audio_and_payoff(cls, project: Dict[str, Any], scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
        warnings = []
        score = 100

        if not scenes:
            return {"score": 50, "payoff_delivered": False, "warnings": []}

        last_scene = scenes[-1]
        text = (last_scene.get("narration_text") or last_scene.get("caption_text") or "").lower()
        has_payoff = any(kw in text for kw in PAYOFF_KEYWORDS)

        if not has_payoff:
            score -= 15
            warnings.append({
                "category": "RETENTION",
                "severity": "SUGGESTION",
                "message": "Closing scene lacks a punchy philosophical or tangible takeaway."
            })

        narration_mode = project.get("narration_mode", "silent")
        if narration_mode == "silent":
            score -= 15
            warnings.append({
                "category": "AUDIO",
                "severity": "SUGGESTION",
                "message": "Video uses silent narration mode. Spoken narration significantly improves retention."
            })

        return {
            "score": max(30, score),
            "payoff_delivered": has_payoff,
            "narration_mode": narration_mode,
            "warnings": warnings
        }
