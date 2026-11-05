"""
Lexicon Repository (Phase 1: Global Only).
"""

from __future__ import annotations

import logging
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas_lexicon import LexiconMatch

logger = logging.getLogger(__name__)


class LexiconRepo:
    """Repository for querying the RAG Lexicon tables.
    Phase 1: STRICTLY enforces Global-only queries (tenant_id IS NULL).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def version(self) -> str:
        """
        Reads `global_lexicon_version` from rag_lexicon_meta.
        Fail-soft: returns '0' if missing/error, enabling the app to start even if seed failed.
        """
        stmt = text("""
            SELECT value 
            FROM rag_lexicon_meta 
            WHERE key = 'global_lexicon_version'
        """)
        try:
            result = await self.session.execute(stmt)
            row = result.fetchone()
            if row:
                return str(row.value)
            return "0"
        except Exception as e:
            logger.warning("Failed to fetch global_lexicon_version, defaulting to '0': %s", e)
            return "0"

    async def match(
        self,
        normalized: str,
        normalized_no_diacritic: str,
        tenant_id: Optional[str] = None,
        limit: int = 50
    ) -> List[LexiconMatch]:
        """
        Matches a term against the global lexicon.
        Enforces tenant_id IS NULL unconditionally for Phase 1.
        Filters for active terms, matches strictly by alias_norm.
        Orders by weight DESC, length(alias) DESC.
        """
        stmt = text("""
            SELECT alias, canonical, term_type, weight
            FROM rag_lexicon
            WHERE tenant_id IS NULL
              AND status = 'active'
              AND alias_norm = :alias_norm
            ORDER BY weight DESC, LENGTH(alias) DESC
            LIMIT :limit
        """)
        
        matches: List[LexiconMatch] = []
        try:
            result = await self.session.execute(
                stmt, 
                {"alias_norm": normalized_no_diacritic, "limit": limit}
            )
            rows = result.fetchall()
            
            for row in rows:
                matches.append(
                    LexiconMatch(
                        alias=row.alias,
                        canonical=row.canonical,
                        term_type=row.term_type,
                        weight=row.weight
                    )
                )
        except Exception as e:
            logger.error("Lexicon match failed: %s", e)
            # Fail-soft on match ensures the rest of RAG pipeline continues seamlessly
        
        return matches
