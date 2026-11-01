"""Visual asset management: priority-based retrieval, Wikimedia/NASA fetchers, and procedural infographics."""

import os
import re
import uuid
import hashlib
import logging
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

import httpx
from PIL import Image, ImageDraw, ImageFont

from backend.app.config import MEDIA_DIR, DB_PATH
from backend.app.db.repository import save_asset_provenance
from backend.app.media.assets import (
    ALLOWED_IMAGE_EXTS,
    MAX_IMAGE_SIZE_BYTES,
    sanitize_and_validate_path,
    generate_default_scene_background
)

logger = logging.getLogger("visual_adapters")

PERMISSIVE_LICENSES = {
    "public domain", "cc0", "cc-zero", "cc by", "cc by 2.0", "cc by 2.5", 
    "cc by 3.0", "cc by 4.0", "cc by-sa", "cc by-sa 2.0", "cc by-sa 3.0", 
    "cc by-sa 4.0", "pd", "nasa", "usgov"
}

class VisualAssetResult:
    """Represents a resolved and validated asset (image or video) with full provenance."""
    def __init__(
        self,
        local_path: Path,
        asset_type: str,
        sha256_checksum: str,
        source_url: Optional[str] = None,
        author: Optional[str] = None,
        license: Optional[str] = None,
        attribution_text: Optional[str] = None,
        associated_claim_id: Optional[str] = None,
        source_asset_id: Optional[str] = None,
        source_page_url: Optional[str] = None,
        license_url: Optional[str] = None,
        media_type: str = "image",
        original_width: Optional[int] = None,
        original_height: Optional[int] = None,
        original_duration: Optional[float] = None,
        file_size_bytes: Optional[int] = None,
        rights_status: str = "VERIFIED_FREE",
        crop_transform: Optional[str] = None,
        selection_reason: Optional[str] = None
    ):
        self.local_path = local_path
        self.asset_type = asset_type
        self.sha256_checksum = sha256_checksum
        self.source_url = source_url
        self.author = author
        self.license = license
        self.attribution_text = attribution_text
        self.associated_claim_id = associated_claim_id
        self.source_asset_id = source_asset_id
        self.source_page_url = source_page_url
        self.license_url = license_url
        self.media_type = media_type
        self.original_width = original_width
        self.original_height = original_height
        self.original_duration = original_duration
        self.file_size_bytes = file_size_bytes
        self.rights_status = rights_status
        self.crop_transform = crop_transform
        self.selection_reason = selection_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "local_path": str(self.local_path),
            "asset_type": self.asset_type,
            "sha256_checksum": self.sha256_checksum,
            "source_url": self.source_url,
            "author": self.author,
            "license": self.license,
            "attribution_text": self.attribution_text,
            "associated_claim_id": self.associated_claim_id,
            "source_asset_id": self.source_asset_id,
            "source_page_url": self.source_page_url,
            "license_url": self.license_url,
            "media_type": self.media_type,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "original_duration": self.original_duration,
            "file_size_bytes": self.file_size_bytes,
            "rights_status": self.rights_status,
            "crop_transform": self.crop_transform,
            "selection_reason": self.selection_reason
        }

class BaseVisualAssetAdapter(ABC):
    @abstractmethod
    def resolve_asset(
        self,
        project_id: str,
        scene: Dict[str, Any],
        query: str,
        width: int = 1080,
        height: int = 1920
    ) -> Optional[VisualAssetResult]:
        """Resolves or generates a visual asset for a given scene."""
        pass

class UserProvidedAssetAdapter(BaseVisualAssetAdapter):
    """Priority 1: User-uploaded asset explicitly assigned to the scene."""

    def resolve_asset(
        self,
        project_id: str,
        scene: Dict[str, Any],
        query: str,
        width: int = 1080,
        height: int = 1920
    ) -> Optional[VisualAssetResult]:
        visual_path = scene.get("visual_asset_path")
        if not visual_path:
            return None

        p = Path(visual_path)
        if not p.exists() or not p.is_file():
            return None

        # Verify extension and size
        ext = p.suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            return None

        size = p.stat().st_size
        if size == 0 or size > MAX_IMAGE_SIZE_BYTES:
            return None

        # Check path containment
        try:
            sanitize_and_validate_path(p.parent, p.name)
        except Exception:
            return None

        hasher = hashlib.sha256()
        with p.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        checksum = hasher.hexdigest()

        return VisualAssetResult(
            local_path=p,
            asset_type="USER_UPLOAD",
            sha256_checksum=checksum,
            source_url=f"file://{p}",
            author="User Upload",
            license="User Provided",
            attribution_text=f"User asset: {p.name}",
            associated_claim_id=(scene.get("supporting_claim_ids") or [None])[0] if scene.get("supporting_claim_ids") else None
        )

class WikimediaNasaAssetAdapter(BaseVisualAssetAdapter):
    """
    Priority 2: Validated external images from NASA and Wikimedia Commons.
    Enforces licensing verification, timeout, size limits, and content-type checks.
    """

    def __init__(self, timeout_sec: float = 8.0, max_download_bytes: int = 15 * 1024 * 1024):
        self.timeout_sec = timeout_sec
        self.max_download_bytes = max_download_bytes

    def resolve_asset(
        self,
        project_id: str,
        scene: Dict[str, Any],
        query: str,
        width: int = 1080,
        height: int = 1920
    ) -> Optional[VisualAssetResult]:
        # Search NASA API first if space/physics topic
        clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip()
        if not clean_q:
            clean_q = scene.get("scene_title", "Science")

        asset = self._search_nasa(project_id, scene, clean_q)
        if asset:
            return asset

        # Fallback to Wikimedia Commons
        asset = self._search_wikimedia(project_id, scene, clean_q)
        if asset:
            return asset

        return None

    def _search_nasa(self, project_id: str, scene: Dict[str, Any], query: str) -> Optional[VisualAssetResult]:
        api_url = f"https://images-api.nasa.gov/search?q={urllib.parse.quote(query)}&media_type=image"
        try:
            with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
                resp = client.get(api_url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                items = data.get("collection", {}).get("items", [])
                if not items:
                    return None

                for item in items[:3]:
                    data_entry = (item.get("data") or [{}])[0]
                    nasa_id = data_entry.get("nasa_id", "nasa_asset")
                    title = data_entry.get("title", query)
                    photographer = data_entry.get("photographer") or data_entry.get("center") or "NASA"
                    links = item.get("links", [])
                    img_url = next((l.get("href") for l in links if l.get("render") == "image"), None)
                    if not img_url:
                        continue

                    downloaded = self._download_and_verify(
                        project_id=project_id,
                        url=img_url,
                        asset_prefix=f"nasa_{nasa_id[:12]}"
                    )
                    if downloaded:
                        p, sha256 = downloaded
                        return VisualAssetResult(
                            local_path=p,
                            asset_type="NASA",
                            sha256_checksum=sha256,
                            source_url=img_url,
                            author=photographer,
                            license="NASA Open Media (Public Domain / Free for Educational Use)",
                            attribution_text=f"NASA / {photographer} - '{title}'",
                            associated_claim_id=(scene.get("supporting_claim_ids") or [None])[0] if scene.get("supporting_claim_ids") else None
                        )
        except Exception as e:
            logger.debug(f"NASA image search failed: {e}")
            return None
        return None

    def _search_wikimedia(self, project_id: str, scene: Dict[str, Any], query: str) -> Optional[VisualAssetResult]:
        api_url = (
            "https://commons.wikimedia.org/w/api.php?"
            "action=query&generator=search&"
            f"gsrsearch={urllib.parse.quote(query)}&"
            "gsrlimit=5&prop=imageinfo&"
            "iiprop=url|size|mime|extmetadata&format=json"
        )
        try:
            with httpx.Client(timeout=self.timeout_sec, headers={"User-Agent": "AIShortsFactory/1.0"}, follow_redirects=True) as client:
                resp = client.get(api_url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                if not pages:
                    return None

                for page_id, page_info in pages.items():
                    imageinfo = (page_info.get("imageinfo") or [{}])[0]
                    file_url = imageinfo.get("url")
                    mime = imageinfo.get("mime", "")
                    if not file_url or mime not in ("image/jpeg", "image/png", "image/webp"):
                        continue

                    # Check extmetadata license
                    extmeta = imageinfo.get("extmetadata", {})
                    lic_name = extmeta.get("LicenseShortName", {}).get("value", "").lower()
                    artist = extmeta.get("Artist", {}).get("value", "Wikimedia Contributor")
                    # Strip HTML from artist
                    artist = re.sub(r'<[^>]+>', '', artist).strip() or "Wikimedia Commons"

                    is_permissive = any(pl in lic_name for pl in PERMISSIVE_LICENSES)
                    if not is_permissive:
                        continue

                    downloaded = self._download_and_verify(
                        project_id=project_id,
                        url=file_url,
                        asset_prefix=f"wiki_{page_id}"
                    )
                    if downloaded:
                        p, sha256 = downloaded
                        return VisualAssetResult(
                            local_path=p,
                            asset_type="WIKIMEDIA",
                            sha256_checksum=sha256,
                            source_url=file_url,
                            author=artist,
                            license=lic_name.upper(),
                            attribution_text=f"Wikimedia Commons / {artist} (License: {lic_name.upper()})",
                            associated_claim_id=(scene.get("supporting_claim_ids") or [None])[0] if scene.get("supporting_claim_ids") else None
                        )
        except Exception as e:
            logger.debug(f"Wikimedia search failed: {e}")
            return None
        return None

    def _download_and_verify(self, project_id: str, url: str, asset_prefix: str) -> Optional[tuple[Path, str]]:
        try:
            target_dir = MEDIA_DIR / "projects" / project_id / "downloads"
            target_dir.mkdir(parents=True, exist_ok=True)

            with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        return None

                    content_type = resp.headers.get("content-type", "").lower()
                    if not any(ct in content_type for ct in ("image/jpeg", "image/png", "image/webp")):
                        return None

                    hasher = hashlib.sha256()
                    raw_chunks = []
                    total_bytes = 0

                    for chunk in resp.iter_bytes(chunk_size=16384):
                        total_bytes += len(chunk)
                        if total_bytes > self.max_download_bytes:
                            return None
                        hasher.update(chunk)
                        raw_chunks.append(chunk)

                    sha256 = hasher.hexdigest()
                    ext = ".jpg" if "jpeg" in content_type else (".png" if "png" in content_type else ".webp")
                    dest_file = target_dir / f"{asset_prefix}_{sha256[:10]}{ext}"

                    with dest_file.open("wb") as f:
                        for chunk in raw_chunks:
                            f.write(chunk)

                    # Validate with PIL that it is a real image
                    with Image.open(dest_file) as im:
                        im.verify()

                    return dest_file, sha256
        except Exception as e:
            logger.debug(f"Asset download/verification failed for {url}: {e}")
            return None

class ProceduralGraphicAdapter(BaseVisualAssetAdapter):
    """
    Priority 3: Procedural diagram generator producing vector-grade, educational 9:16 vertical graphics.
    Zero external downloads, zero API cost, instantaneous generation.
    """

    def resolve_asset(
        self,
        project_id: str,
        scene: Dict[str, Any],
        query: str,
        width: int = 1080,
        height: int = 1920
    ) -> Optional[VisualAssetResult]:
        target_dir = MEDIA_DIR / "projects" / project_id / "procedural"
        target_dir.mkdir(parents=True, exist_ok=True)

        scene_idx = scene.get("scene_index", 0)
        title = scene.get("scene_title", "Concept")
        narration = scene.get("narration_text", "")
        theme = self._detect_theme(title + " " + narration + " " + query)

        out_path = target_dir / f"scene_{scene_idx}_{theme}.png"
        self._generate_diagram(out_path, theme, title, narration, width, height)

        hasher = hashlib.sha256()
        with out_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        checksum = hasher.hexdigest()

        return VisualAssetResult(
            local_path=out_path,
            asset_type="PROCEDURAL",
            sha256_checksum=checksum,
            source_url="procedural://engine/scientific_graphics",
            author="AI Shorts Procedural Graphics",
            license="CC0 (Procedural Engine Generated)",
            attribution_text=f"Procedural Infographic: '{theme.replace('_', ' ').title()}'",
            associated_claim_id=(scene.get("supporting_claim_ids") or [None])[0] if scene.get("supporting_claim_ids") else None
        )

    def _detect_theme(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ("gravity", "spacetime", "warp", "curvature", "einstein")):
            return "gravity_spacetime_well"
        elif any(w in t for w in ("altitude", "mountain", "sea level", "elevation", "height", "clock", "feet", "head")):
            return "altitude_clock_dilation"
        elif any(w in t for w in ("gps", "satellite", "orbit", "relativity", "microsecond", "drift")):
            return "gps_orbital_relativity"
        elif any(w in t for w in ("atomic", "optical", "nist", "millimeter", "measurement", "fountain")):
            return "atomic_clock_precision"
        else:
            return "quantum_time_metric"

    def _generate_diagram(
        self,
        out_path: Path,
        theme: str,
        title: str,
        narration: str,
        width: int,
        height: int
    ) -> None:
        im = Image.new("RGBA", (width, height), (10, 15, 30, 255)) # Dark navy
        draw = ImageDraw.Draw(im)

        # Background gradient / grid lines
        for y in range(0, height, 80):
            draw.line([(0, y), (width, y)], fill=(20, 32, 55, 120), width=1)
        for x in range(0, width, 80):
            draw.line([(x, 0), (x, height)], fill=(20, 32, 55, 120), width=1)

        # Header badge
        draw.rounded_rectangle([(80, 180), (width - 80, 260)], radius=15, fill=(16, 28, 52, 220), outline=(0, 200, 255, 180), width=2)
        draw.text((120, 205), f"TOPIC INTELLIGENCE: {title.upper()[:35]}", fill=(0, 220, 255, 255))

        # Render theme-specific central graphic
        cy = height // 2 - 50
        cx = width // 2

        if theme == "altitude_clock_dilation":
            # Mountain vs Sea level altitude comparison
            # Ground & Sea
            draw.rectangle([(100, cy + 320), (width - 100, cy + 360)], fill=(0, 110, 180, 255))
            draw.text((120, cy + 375), "SEA LEVEL (Stronger Gravity -> SLOWER CLOCK)", fill=(0, 220, 255, 255))

            # Mountain peak
            mountain_points = [(150, cy + 320), (cx, cy - 180), (width - 150, cy + 320)]
            draw.polygon(mountain_points, fill=(35, 45, 65, 255), outline=(100, 120, 150, 255))
            draw.polygon([(cx - 70, cy - 80), (cx, cy - 180), (cx + 70, cy - 80)], fill=(220, 230, 255, 255)) # Snow cap
            draw.text((cx - 150, cy - 240), "ALTITUDE (Weaker Gravity -> FASTER)", fill=(255, 180, 50, 255))

            # Clocks
            # Clock 1: Mountain
            draw.ellipse([(cx - 60, cy - 30), (cx + 60, cy + 90)], outline=(255, 180, 50, 255), width=4)
            draw.line([(cx, cy + 30), (cx, cy)], fill=(255, 180, 50, 255), width=3)
            draw.line([(cx, cy + 30), (cx + 25, cy + 30)], fill=(255, 180, 50, 255), width=3)

            # Clock 2: Sea level
            draw.ellipse([(cx + 240, cy + 220), (cx + 340, cy + 320)], outline=(0, 220, 255, 255), width=4)
            draw.line([(cx + 290, cy + 270), (cx + 290, cy + 245)], fill=(0, 220, 255, 255), width=3)
            draw.line([(cx + 290, cy + 270), (cx + 310, cy + 270)], fill=(0, 220, 255, 255), width=3)

            # Formula callout
            draw.rounded_rectangle([(120, cy + 460), (width - 120, cy + 560)], radius=12, fill=(15, 25, 45, 230), outline=(0, 220, 255, 150), width=2)
            draw.text((150, cy + 485), "EINSTEIN'S GENERAL RELATIVITY:", fill=(255, 255, 255, 255))
            draw.text((150, cy + 515), "Delta t / t  =  g * h / c^2  (Gravitational Potential)", fill=(0, 240, 255, 255))

        elif theme == "gps_orbital_relativity":
            # Earth at bottom, satellite in orbit
            draw.ellipse([(cx - 300, cy + 250), (cx + 300, cy + 850)], fill=(15, 50, 90, 255), outline=(0, 180, 255, 255), width=3)
            draw.text((cx - 80, cy + 380), "EARTH SURFACE", fill=(200, 230, 255, 255))

            # Orbital path
            draw.arc([(cx - 450, cy - 350), (cx + 450, cy + 450)], start=200, end=340, fill=(100, 120, 180, 180), width=2)

            # Satellite icon
            sat_x, sat_y = cx, cy - 250
            draw.rectangle([(sat_x - 40, sat_y - 25), (sat_x + 40, sat_y + 25)], fill=(200, 200, 210, 255), outline=(255, 255, 255, 255), width=2)
            # Solar panels
            draw.rectangle([(sat_x - 120, sat_y - 15), (sat_x - 40, sat_y + 15)], fill=(0, 120, 220, 255), outline=(0, 200, 255, 255), width=2)
            draw.rectangle([(sat_x + 40, sat_y - 15), (sat_x + 120, sat_y + 15)], fill=(0, 120, 220, 255), outline=(0, 200, 255, 255), width=2)

            # Relativity metrics card
            draw.rounded_rectangle([(100, cy + 50), (width - 100, cy + 220)], radius=12, fill=(18, 28, 48, 240), outline=(255, 180, 50, 200), width=2)
            draw.text((130, cy + 70), "GPS RELATIVISTIC CORRECTION (+38.6 us / day):", fill=(255, 200, 80, 255))
            draw.text((130, cy + 110), "+45.9 us/day (General Relativity: Weaker Gravity)", fill=(0, 240, 180, 255))
            draw.text((130, cy + 150), "-7.2 us/day  (Special Relativity: Orbital Speed)", fill=(255, 100, 100, 255))

        elif theme == "gravity_spacetime_well":
            # Spacetime Curvature Funnel
            for r in range(40, 360, 40):
                draw.ellipse([(cx - r, cy - int(r * 0.5)), (cx + r, cy + int(r * 0.5))], outline=(0, 180, 255, max(40, 255 - r // 2)), width=2)
            # Center mass
            draw.ellipse([(cx - 70, cy - 70), (cx + 70, cy + 70)], fill=(0, 140, 255, 255), outline=(255, 255, 255, 255), width=4)
            draw.text((cx - 50, cy - 10), "MASS / GRAVITY", fill=(255, 255, 255, 255))

            # Curvature annotations
            draw.rounded_rectangle([(100, cy + 300), (width - 100, cy + 420)], radius=12, fill=(15, 25, 45, 230), outline=(0, 220, 255, 180), width=2)
            draw.text((130, cy + 325), "SPACETIME CURVATURE:", fill=(255, 255, 255, 255))
            draw.text((130, cy + 360), "Gravity curves spacetime: closer clocks tick slower.", fill=(0, 230, 255, 255))

        else:
            # Atomic clock / precision optics theme
            draw.ellipse([(cx - 180, cy - 180), (cx + 180, cy + 180)], outline=(0, 230, 255, 255), width=4)
            for angle in range(0, 360, 30):
                import math
                rad = math.radians(angle)
                x1 = cx + int(140 * math.cos(rad))
                y1 = cy + int(140 * math.sin(rad))
                x2 = cx + int(170 * math.cos(rad))
                y2 = cy + int(170 * math.sin(rad))
                draw.line([(x1, y1), (x2, y2)], fill=(0, 230, 255, 255), width=3)
            draw.text((cx - 100, cy - 15), "OPTICAL LATTICE", fill=(255, 255, 255, 255))

            draw.rounded_rectangle([(100, cy + 280), (width - 100, cy + 400)], radius=12, fill=(15, 25, 45, 230), outline=(0, 220, 255, 180), width=2)
            draw.text((130, cy + 305), "NIST LAB VERIFICATION:", fill=(255, 255, 255, 255))
            draw.text((130, cy + 345), "Measures time dilation across a single millimeter height.", fill=(0, 230, 255, 255))

        # Bottom quote / takeaway card
        draw.rounded_rectangle([(80, height - 340), (width - 80, height - 200)], radius=15, fill=(15, 25, 45, 240), outline=(255, 255, 255, 60), width=1)
        draw.text((110, height - 315), "FACT SUMMARY:", fill=(255, 200, 80, 255))
        wrapped_summary = (narration[:90] + "...") if len(narration) > 90 else narration
        draw.text((110, height - 280), wrapped_summary, fill=(220, 230, 240, 255))

        im.save(str(out_path), "PNG")

class CompositeVisualResolver:
    """
    Coordinates priority-based visual asset resolution:
    1. User Uploads
    2. Wikimedia / NASA
    3. Procedural Graphics
    4. Fallback Default Backgrounds
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.user_adapter = UserProvidedAssetAdapter()
        self.wikimedia_nasa = WikimediaNasaAssetAdapter()
        self.procedural = ProceduralGraphicAdapter()

    def resolve_for_scene(
        self,
        project_id: str,
        scene: Dict[str, Any],
        topic_query: str,
        width: int = 1080,
        height: int = 1920
    ) -> VisualAssetResult:
        scene_idx = scene.get("scene_index", 0)
        query = f"{topic_query} {scene.get('scene_title', '')}"

        # 1. User Uploaded
        res = self.user_adapter.resolve_asset(project_id, scene, query, width, height)
        if res:
            if not res.selection_reason:
                res.selection_reason = f"User uploaded visual asset"
            self._persist_provenance(project_id, scene_idx, res)
            return res

        # 2. Wikimedia / NASA
        res = self.wikimedia_nasa.resolve_asset(project_id, scene, query, width, height)
        if res:
            if not res.selection_reason:
                res.selection_reason = f"Authentic image from {res.asset_type} with Ken Burns motion"
            self._persist_provenance(project_id, scene_idx, res)
            return res

        # 3. Procedural Infographic
        res = self.procedural.resolve_asset(project_id, scene, query, width, height)
        if res:
            if not res.selection_reason:
                res.selection_reason = "Procedural diagram graphic with Ken Burns motion"
            self._persist_provenance(project_id, scene_idx, res)
            return res

        # 4. Fallback Default Background
        fallback_path = generate_default_scene_background(
            project_id=project_id,
            scene_index=scene_idx,
            title=scene.get("scene_title", "Scene"),
            width=width,
            height=height
        )
        hasher = hashlib.sha256()
        with fallback_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        fallback_res = VisualAssetResult(
            local_path=fallback_path,
            asset_type="FALLBACK",
            sha256_checksum=hasher.hexdigest(),
            source_url="internal://fallback/default_scene",
            author="Internal Default Generator",
            license="Public Domain / CC0",
            attribution_text="Default Solid Background",
            associated_claim_id=None,
            selection_reason="Default solid background fallback"
        )
        self._persist_provenance(project_id, scene_idx, fallback_res)
        return fallback_res

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
            logger.warning(f"Failed to persist asset provenance: {e}")
        return prov_id
