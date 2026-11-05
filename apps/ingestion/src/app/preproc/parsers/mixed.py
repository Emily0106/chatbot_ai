# preproc/parsers/mixed.py
from __future__ import annotations

import logging
from typing import List, Tuple, Any

from app.core.canonical_models import (
    CanonicalChunk,
    CanonicalStructuredRow,
    CanonicalDocument,
    ExtractedBlock,
    ExtractedDoc,
    DocCategory
)
from app.preproc.pipeline.interfaces import (
    IngestMeta,
    ClassificationResult,
    ParsedDoc, # Not strictly in interface but implied return type
)

logger = logging.getLogger(__name__)

class MixedParser:
    """
    Doc-level parser for 'Mixed' category logic (or Orchestrator routing).
    In the "Production 2025" plan, the Mixed logic is largely handled by the 
    block-level routing in the Orchestrator itself.
    
    However, if we strictly need a 'DocParser' for the 'mixed' category 
    that fits the registry interface, it can simply act as a pass-through 
    or contain specific logic for when the Orchestrator delegates "whole doc" parsing.
    
    For now, this is a stub that logs a warning because the Orchestrator 
    is expected to handle blocks individually.
    """

    def parse(
        self,
        extracted: ExtractedDoc,
        meta: IngestMeta,
        classification: ClassificationResult,
        doc: CanonicalDocument,
    ) -> Tuple[List[CanonicalChunk], List[CanonicalStructuredRow]]:
        
        # The Orchestrator calls specific block parsers (Narrative/TableList) 
        # based on block kind. Usually, it won't call a "MixedParser" for the whole doc 
        # unless we want to do some global consolidation here.
        
        # We return empty here so the Orchestrator loop (if it invokes this) 
        # doesn't duplicate data. 
        # Real mixed-routing happens in Orchestrator.process().
        
        logger.info("MixedParser invoked for doc_id=%s. Delegating to block-level routing.", doc.doc_id)
        return [], []
