import pytest
from unittest.mock import MagicMock
from app.core.canonical_models import ExtractedBlock, ExtractedBlockKind, ExtractedDoc
from app.preproc.extractors.docling_extractor import DoclingExtractor, DoclingExtractorConfig
from app.preproc.extractors.fast_pdf_extractor import FastPdfExtractor
from app.preproc.pipeline.interfaces import IngestMeta
from app.preproc.utils.citations import CitationContext, citation_for_page_block

def test_citation_page_index_0_based():
    """Verify that citation_for_page_block uses 0-based index correctly."""
    ctx = CitationContext(source_uri="test", checksum="abc", mime_type="application/pdf")
    
    # Page 1 (index 0)
    cit0 = citation_for_page_block(ctx, page_index=0, anchor="p1")
    assert cit0.locator.page_start == 0
    assert cit0.locator.page_end == 0
    # short() adds 1 for display. 
    # Since anchor is also "p1", short() returns "p1 | p1".
    assert cit0.locator.short() == "p1 | p1"

    # Page 2 (index 1)
    cit1 = citation_for_page_block(ctx, page_index=1, anchor="p2")
    assert cit1.locator.page_start == 1
    assert cit1.locator.page_end == 1
    assert cit1.locator.short() == "p2 | p2"

def test_fast_pdf_extractor_0_based_index():
    """Verify FastPdfExtractor produces 0-based page_index."""
    # Mock pypdf and Path
    with pytest.MonkeyPatch.context() as m:
        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = [MagicMock(), MagicMock()] # 2 pages
        mock_reader.pages[0].extract_text.return_value = "Page 1 text"
        mock_reader.pages[1].extract_text.return_value = "Page 2 text"
        
        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.return_value = mock_reader
        m.setattr("app.preproc.extractors.fast_pdf_extractor.pypdf", mock_pypdf)
        
        # Mock Path.exists and is_file
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = True
        m.setattr("app.preproc.extractors.fast_pdf_extractor.Path", lambda x: mock_path)
        
        extractor = FastPdfExtractor()
        meta = IngestMeta(
            tenant_id="T1",
            doc_type="law",
            scope="public",
            security_level=1,
            commune_id="123",
            checksum="abc",
            mime_type="application/pdf",
            source_uri="test",
            title="test",
            pipeline_version="1",
        )
        
        doc = extractor.extract("dummy.pdf", meta)
        
        assert len(doc.blocks) == 2
        
        # Block 1: page_index should be 0, anchor p1
        b0 = doc.blocks[0]
        assert b0.page_index == 0
        assert b0.anchor == "p1"
        
        # Block 2: page_index should be 1, anchor p2
        b1 = doc.blocks[1]
        assert b1.page_index == 1
        assert b1.anchor == "p2"
