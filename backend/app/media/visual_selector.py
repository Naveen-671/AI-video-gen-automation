"""
Scene-Aware Visual Selector for Stage 5 Hybrid Engine.
Selects between authentic NASA/Wikimedia video clips, high-craft procedural diagrams,
and high-resolution still images with Ken Burns motion, based on narrative content.
Maintains fail-closed fallbacks and full provenance tracking.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.repository import save_asset_provenance
from backend.app.media.reframing import VideoReframer
from backend.app.media.video_adapters import NASAVideoAdapter, WikimediaVideoAdapter
from backend.app.media.visual_adapters import (
    CompositeVisualResolver,
    ProceduralGraphicAdapter,
    VisualAssetResult,
)

logger = logging.getLogger("visual_selector")

OBSERVATIONAL_KEYWORDS = {
    "orbit", "earth", "satellite", "space", "galaxy", "black hole",
    "cosmic", "universe", "planet", "stars", "gravity field", "iss",
    "astronaut", "telescope", "hubble", "webb", "curvature", "spacetime",
    "spacecraft", "solar", "sun", "moon", "atmosphere", "celestial"
}

PROCEDURAL_KEYWORDS = {
    "formula", "equation", "math", "millimeter", "atomic clock",
    "optical lattice", "difference", "graph", "diagram", "ratio",
    "nanosecond", "measurement", "infographic", "physics law", "einstein",
    "relativity formula", "tick rate", "laboratory", "nist"
}


class SceneVisualSelector:
    """Intelligently classifies scene beats and resolves the optimal visual modality."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.nasa_video = NASAVideoAdapter()
        self.wikimedia_video = WikimediaVideoAdapter()
        self.procedural = ProceduralGraphicAdapter()
        self.composite_resolver = CompositeVisualResolver(db_path=db_path)
        self.reframer = VideoReframer()

    def classify_scene_modality(self, scene: Dict[str, Any], topic: str) -> str:
        """
        Classifies scene beat into:
        - 'VIDEO': Observational, cosmic, satellite, or Earth footage
        - 'PROCEDURAL': Formulas, lab measurements, atomic clocks, precision comparisons
        - 'IMAGE_KEN_BURNS': General scenes best served by curated stills
        """
        text_corpus = " ".join([
            topic,
            scene.get("scene_title", ""),
            scene.get("narration", ""),
            scene.get("visual_description", "")
        ]).lower()

        tokens = set(re.findall(r'\b[a-z]{3,}\b', text_corpus))

        obs_score = len(tokens.intersection(OBSERVATIONAL_KEYWORDS))
        proc_score = len(tokens.intersection(PROCEDURAL_KEYWORDS))

        if proc_score > obs_score and proc_score >= 1:
            return "PROCEDURAL"
        elif obs_score >= 1:
            return "VIDEO"
        else:
            return "IMAGE_KEN_BURNS"

    def resolve_visual_for_scene(
        self,
        project_id: str,
        scene: Dict[str, Any],
        topic: str,
        duration: float,
        enable_video: bool = True,
        anchor: str = "center"
    ) -> VisualAssetResult:
        """
        Resolves asset for a single scene beat.
        If video is selected and enabled, retrieves and reframes the video to 1080x1920.
        Gracefully falls back to procedural diagram or Ken Burns image on any failure.
        """
        scene_idx = scene.get("scene_index", 0)
        claim_id = (scene.get("supporting_claim_ids") or [None])[0] if scene.get("supporting_claim_ids") else None
        modality = self.classify_scene_modality(scene, topic)

        # 1. Procedural beat preferred
        if modality == "PROCEDURAL":
            reason = f"Mathematical / precision beat for '{scene.get('scene_title')}'"
            res = self.procedural.resolve_asset(
                project_id=project_id,
                scene=scene,
                query=f"{topic} {scene.get('scene_title', '')}"
            )
            if res:
                res.selection_reason = reason
                self._persist_provenance(project_id, scene_idx, res)
                return res

        # 2. Authentic Video beat preferred
        if modality == "VIDEO" and enable_video:
            query = f"{topic} {scene.get('scene_title', '')}"
            # Try NASA video first
            video_res = self.nasa_video.search_video(
                project_id=project_id,
                query=query,
                scene_index=scene_idx,
                associated_claim_id=claim_id
            )
            # Try Wikimedia video if NASA yields nothing
            if not video_res:
                video_res = self.wikimedia_video.search_video(
                    project_id=project_id,
                    query=query,
                    scene_index=scene_idx,
                    associated_claim_id=claim_id
                )

            if video_res:
                try:
                    # Reframe video to vertical 1080x1920 clip
                    reframed_dir = MEDIA_DIR / project_id / "reframed_clips"
                    reframed_dir.mkdir(parents=True, exist_ok=True)
                    reframed_path = reframed_dir / f"scene_{scene_idx:02d}_reframed.mp4"

                    self.reframer.reframe_clip(
                        input_video_path=video_res.local_path,
                        output_clip_path=reframed_path,
                        duration=duration,
                        anchor=anchor
                    )

                    # Update local_path to the reframed clip
                    video_res.local_path = reframed_path
                    video_res.crop_transform = f"VideoReframer(anchor={anchor}, 1080x1920, 30fps)"
                    video_res.selection_reason = f"Authentic public domain video chosen for observational beat '{scene.get('scene_title')}'"
                    self._persist_provenance(project_id, scene_idx, video_res)
                    return video_res
                except Exception as reframe_err:
                    logger.warning(f"Video reframing failed for scene {scene_idx}: {reframe_err}. Falling back to image.")

        # 3. Fallback to composite resolver (User upload -> Wikimedia/NASA image -> Procedural -> Solid)
        return self.composite_resolver.resolve_for_scene(
            project_id=project_id,
            scene=scene,
            topic_query=topic
        )

    def _persist_provenance(self, project_id: str, scene_idx: int, res: VisualAssetResult) -> str:
        prov_id = str(uuid.uuid4())
        try:
            save_asset_provenance(
                provenance_id=prov_id,
                project_id=project_id,
                scene_index=scene_idx,
                asset_type=res.asset_type,
                local_path=str(res.local_path),
                sha256_checksum=res.sha256_checksum,
                source_url=res.source_url,
                author=res.author,
                license=res.license,
                attribution_text=res.attribution_text,
                associated_claim_id=res.associated_claim_id,
                source_asset_id=res.source_asset_id,
                source_page_url=res.source_page_url,
                license_url=res.license_url,
                media_type=res.media_type,
                original_width=res.original_width,
                original_height=res.original_height,
                original_duration=res.original_duration,
                file_size_bytes=res.file_size_bytes,
                rights_status=res.rights_status,
                crop_transform=res.crop_transform,
                selection_reason=res.selection_reason,
                db_path=self.db_path
            )
        except Exception as e:
            logger.warning(f"Failed to persist asset provenance in selector: {e}")
        return prov_id
