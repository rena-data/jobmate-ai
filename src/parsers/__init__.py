from parsers.base import BaseParser, JobPost
from parsers.wanted import WantedParser
from parsers.saramin import SaraminParser
from parsers.fallback import FallbackParser

__all__ = ["BaseParser", "JobPost", "WantedParser", "SaraminParser", "FallbackParser"]
