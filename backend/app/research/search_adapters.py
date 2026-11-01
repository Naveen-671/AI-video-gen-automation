"""Search adapters for topic intelligence and candidate source discovery."""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

logger = logging.getLogger("research.search")


class CandidateSource(BaseModel):
    """
    Candidate source discovered via search meta-index.
    CRITICAL RULE: The snippet is raw search metadata only; it is NEVER
    presented as independently verified evidence without full document extraction.
    """
    title: str
    url: str
    snippet: str = Field(..., description="Unverified search snippet. Cannot be cited as proof.")


class BaseSearchAdapter(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[CandidateSource]:
        """Discovers candidate URLs for a research query."""
        pass


class DDGSSearchAdapter(BaseSearchAdapter):
    """
    Search adapter using local ddgs (DuckDuckGo Search).
    Zero recurring cost, no API keys, no external credentials required.
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> List[CandidateSource]:
        if not query or not query.strip():
            return []

        try:
            import ddgs
            client = ddgs.DDGS(timeout=self.timeout)
            raw_results = client.text(query.strip(), max_results=max_results)
            candidates: List[CandidateSource] = []
            for item in raw_results:
                url = item.get("href") or item.get("url")
                title = item.get("title") or "Untitled Source"
                snippet = item.get("body") or item.get("snippet") or ""
                if url:
                    candidates.append(CandidateSource(title=title, url=url, snippet=snippet))
            logger.info("DDGS search returned %d candidate sources for query '%s'", len(candidates), query)
            return candidates
        except Exception as e:
            logger.warning("DDGS search query failed for '%s': %s", query, e)
            return []


class MockSearchAdapter(BaseSearchAdapter):
    """
    Deterministic search adapter for offline unit tests, regression suites,
    and predictable benchmarks.
    """

    def __init__(self, custom_results: Optional[Dict[str, List[CandidateSource]]] = None):
        self.custom_results = custom_results or {}

    def search(self, query: str, max_results: int = 5) -> List[CandidateSource]:
        q = query.lower()
        for k, v in self.custom_results.items():
            if k.lower() in q:
                return v[:max_results]

        # Built-in deterministic defaults for domain topics
        if "gravit" in q or "time" in q:
            return [
                CandidateSource(
                    title="Putting Einstein to the Test | NIST",
                    url="https://www.nist.gov/atomic-clocks/putting-einstein-test",
                    snippet="NIST atomic clocks demonstrate that time passes faster at higher elevations where gravity is weaker."
                ),
                CandidateSource(
                    title="Gravitational Time Dilation - Wikipedia",
                    url="https://en.wikipedia.org/wiki/Gravitational_time_dilation",
                    snippet="Gravitational time dilation is an actual difference of elapsed time between two events measured by observers at different gravitational potentials."
                ),
                CandidateSource(
                    title="GPS and Relativity - Astronomy Notes",
                    url="https://www.astronomy.ohio-state.edu/gps-relativity",
                    snippet="Without relativistic time dilation corrections, GPS satellite clocks would drift 38 microseconds daily."
                )
            ][:max_results]
        elif "neutron" in q or "star" in q:
            return [
                CandidateSource(
                    title="Neutron Stars - NASA Science",
                    url="https://science.nasa.gov/astrophysics/focus-areas/neutron-stars",
                    snippet="Neutron stars are the collapsed cores of massive stars, packing more than solar mass into a city-sized sphere."
                ),
                CandidateSource(
                    title="Extreme Density of Degenerate Matter - National Lab",
                    url="https://www.energy.gov/science/doe-explains-neutron-stars",
                    snippet="A single teaspoon of neutron star matter would weigh approximately six billion tons on Earth."
                )
            ][:max_results]
        else:
            return [
                CandidateSource(
                    title=f"Scientific Overview: {query.title()}",
                    url=f"https://open-science.org/research/{query.replace(' ', '_').lower()}",
                    snippet=f"Comprehensive documentation and peer-reviewed studies regarding {query}."
                ),
                CandidateSource(
                    title=f"Principles of {query.title()} - Academic Archive",
                    url=f"https://arxiv.org/abs/example_{query.replace(' ', '_').lower()}",
                    snippet=f"Fundamental experimental observations and theoretical models governing {query}."
                )
            ][:max_results]
