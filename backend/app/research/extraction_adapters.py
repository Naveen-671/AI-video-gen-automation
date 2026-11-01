"""Extraction adapters for reading source content and capturing verified excerpts."""

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

logger = logging.getLogger("research.extraction")


class ExtractedDocument(BaseModel):
    """
    Extracted source content from a primary document URL.
    This content is the only valid basis for verified evidence in FactLedger.
    """
    url: str
    title: str = "Untitled Document"
    published_date: Optional[str] = None
    paragraphs: List[str] = Field(default_factory=list)
    raw_excerpt: str = ""
    http_status: int = 200
    success: bool = True
    error_message: Optional[str] = None


class BaseExtractionAdapter(ABC):
    @abstractmethod
    def extract(self, url: str) -> ExtractedDocument:
        """Retrieves and extracts readable article text and metadata from a URL."""
        pass


class HTTPTextExtractionAdapter(BaseExtractionAdapter):
    """
    Lightweight, headless HTTP extraction adapter using httpx and lxml.
    Zero browser dependencies, zero VRAM usage, consuming < 25 MB RAM.
    Preferred over Crawl4AI/Chromium when primary articles are standard HTML.
    """

    def __init__(self, timeout: float = 10.0, user_agent: str = "AIShortsFactory/1.0 (+research-bot)"):
        self.timeout = timeout
        self.user_agent = user_agent

    def extract(self, url: str) -> ExtractedDocument:
        import httpx
        from lxml import html

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True, verify=True) as client:
                res = client.get(url, headers=headers)
                
            if res.status_code >= 400:
                logger.warning("HTTP extraction failed with status %d for %s", res.status_code, url)
                return ExtractedDocument(
                    url=url,
                    http_status=res.status_code,
                    success=False,
                    error_message=f"HTTP {res.status_code} Error"
                )

            tree = html.fromstring(res.content)

            # 1. Extract title
            title_node = tree.xpath("//title/text()") or tree.xpath("//h1/text()")
            title = title_node[0].strip() if title_node else "Untitled Source"

            # 2. Extract publication date from standard meta tags if present
            pub_date = None
            date_meta = tree.xpath(
                "//meta[@property='article:published_time']/@content | "
                "//meta[@name='publication_date']/@content | "
                "//meta[@name='date']/@content | "
                "//time/@datetime"
            )
            if date_meta:
                pub_date = str(date_meta[0]).strip()[:10]  # YYYY-MM-DD

            # 3. Extract clean body paragraphs, stripping scripts and styles
            for bad in tree.xpath("//script | //style | //nav | //footer | //header | //aside"):
                bad.getparent().remove(bad)

            paragraphs: List[str] = []
            for p in tree.xpath("//p"):
                text = p.text_content().strip()
                # Clean multiple internal whitespaces
                text = re.sub(r"\s+", " ", text)
                if len(text) > 40:  # meaningful sentence/paragraph threshold
                    paragraphs.append(text)

            excerpt = " ".join(paragraphs[:3])[:1000] if paragraphs else ""

            logger.info("Successfully extracted %d paragraphs from %s", len(paragraphs), url)
            return ExtractedDocument(
                url=url,
                title=title,
                published_date=pub_date,
                paragraphs=paragraphs,
                raw_excerpt=excerpt,
                http_status=res.status_code,
                success=len(paragraphs) > 0,
                error_message=None if len(paragraphs) > 0 else "No readable paragraphs found."
            )

        except Exception as e:
            logger.warning("Extraction error for %s: %s", url, e)
            return ExtractedDocument(
                url=url,
                http_status=500,
                success=False,
                error_message=str(e)
            )


class MockExtractionAdapter(BaseExtractionAdapter):
    """
    Deterministic document extraction adapter for offline testing, simulating
    both successful extractions with verified quotes and failure modes.
    """

    def __init__(self, custom_docs: Optional[Dict[str, ExtractedDocument]] = None):
        self.custom_docs = custom_docs or {}

    def extract(self, url: str) -> ExtractedDocument:
        if url in self.custom_docs:
            return self.custom_docs[url]

        # Domain fallbacks for test URLs
        if "nist" in url.lower():
            return ExtractedDocument(
                url=url,
                title="Putting Einstein to the Test | NIST",
                published_date="2022-02-16",
                paragraphs=[
                    "Albert Einstein's general theory of relativity predicts that gravity alters the passage of time.",
                    "Clocks in higher gravitational potentials (farther from the Earth's center of mass) tick faster than clocks closer to Earth.",
                    "In 2022, JILA and NIST physicists measured this time dilation across a height difference of a single millimeter using strontium optical lattice clocks."
                ],
                raw_excerpt="In 2022, JILA and NIST physicists measured this time dilation across a height difference of a single millimeter using strontium optical lattice clocks.",
                http_status=200,
                success=True
            )
        elif "wikipedia" in url.lower():
            return ExtractedDocument(
                url=url,
                title="Gravitational Time Dilation - Wikipedia",
                published_date="2023-10-01",
                paragraphs=[
                    "Gravitational time dilation is a form of time dilation, an actual difference of elapsed time between two events as measured by observers situated at varying distances from a gravitating mass.",
                    "Without software corrections for gravitational time dilation and orbital velocity, GPS satellite clocks would gain approximately 38 microseconds each day, resulting in navigational drift of roughly 11 kilometers daily."
                ],
                raw_excerpt="Without software corrections for gravitational time dilation and orbital velocity, GPS satellite clocks would gain approximately 38 microseconds each day, resulting in navigational drift of roughly 11 kilometers daily.",
                http_status=200,
                success=True
            )
        elif "fail" in url.lower() or "404" in url.lower():
            return ExtractedDocument(
                url=url,
                title="Error 404: Not Found",
                http_status=404,
                success=False,
                error_message="HTTP 404 Not Found"
            )
        else:
            return ExtractedDocument(
                url=url,
                title="General Reference Document",
                published_date="2024-01-15",
                paragraphs=[
                    f"Comprehensive experimental observations regarding {url}.",
                    "Secondary findings confirm initial measurements within standard experimental confidence bounds."
                ],
                raw_excerpt="Secondary findings confirm initial measurements within standard experimental confidence bounds.",
                http_status=200,
                success=True
            )
