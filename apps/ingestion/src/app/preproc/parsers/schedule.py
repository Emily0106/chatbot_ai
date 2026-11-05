from typing import List, Tuple, Dict, Any
from app.preproc.pipeline.interfaces import BaseParser
from app.core.canonical_models import CanonicalChunk, CanonicalStructuredRow

class ScheduleParser(BaseParser):
    def parse_block(self, block: Any, meta: Dict[str, Any], doc_category: str) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        print("Parsing schedule block")
        return [], []
