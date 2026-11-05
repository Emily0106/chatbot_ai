# apps/ingestion/tests/test_smart_router.py
import pytest
from unittest.mock import patch, MagicMock
from app.core.config import GovConfig
from app.utils.pdf_sniffer import sniff_pdf
from app.utils.route_pdf import decide_pdf_lane
from app.preproc.pipeline.orchestrator import IngestionOrchestrator
from app.preproc.pipeline.registry import ToolRegistry
from app.preproc.pipeline.interfaces import IngestMeta
import os

# Mock pypdf to avoid needing real PDF files
@pytest.fixture
def mock_pypdf():
    with patch("app.utils.pdf_sniffer.pypdf") as mock:
        yield mock

def test_sniff_pdf_encrypted(mock_pypdf):
    mock_reader = MagicMock()
    mock_reader.is_encrypted = True
    mock_pypdf.PdfReader.return_value = mock_reader
    
    res = sniff_pdf("dummy.pdf")
    assert res["ok"] is True
    assert res["is_encrypted"] is True

def test_sniff_pdf_digital_short(mock_pypdf):
    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [MagicMock(), MagicMock()] # 2 pages
    mock_reader.pages[0].extract_text.return_value = "A" * 500 # High density
    mock_reader.pages[1].extract_text.return_value = "B" * 500
    mock_pypdf.PdfReader.return_value = mock_reader
    
    with patch("os.path.getsize", return_value=1024):
        res = sniff_pdf("dummy.pdf")
    
    assert res["ok"] is True
    assert res["page_count"] == 2
    assert res["has_text_layer"] is True
    assert res["text_density"] >= 500

def test_decide_lane_fast():
    sniff = {
        "ok": True,
        "is_encrypted": False,
        "page_count": 5,
        "has_text_layer": True,
        "text_density": 300, # > 200
    }
    lane, reason = decide_pdf_lane(sniff)
    assert lane == "fast"
    assert reason == "digital_short"

def test_decide_lane_heavy_scan():
    sniff = {
        "ok": True,
        "is_encrypted": False,
        "page_count": 5,
        "has_text_layer": False, # No text
        "text_density": 10,
    }
    lane, reason = decide_pdf_lane(sniff)
    assert lane == "heavy"

def test_decide_lane_reject_too_large():
    sniff = {
        "ok": True,
        "page_count": 500, # > 200 (MAX_PAGE_COUNT)
    }
    lane, reason = decide_pdf_lane(sniff)
    assert lane == "reject"
    assert reason == "page_limit_exceeded"

# Integration-like tests for Orchestrator routing logic
@patch("app.preproc.pipeline.orchestrator.sniff_pdf")
@patch("app.preproc.pipeline.orchestrator.decide_pdf_lane")
@patch("os.path.getsize")
def test_orchestrator_routes_octet_stream_pdf(mock_getsize, mock_decide, mock_sniff):
    # Setup
    mock_getsize.return_value = 1024
    mock_sniff.return_value = {}
    mock_decide.return_value = ("fast", "test_reason")
    
    registry = MagicMock(spec=ToolRegistry)
    # When get_extractor is called, check if meta has ingest_lane="fast"
    def check_meta(path, meta):
        assert getattr(meta, "ingest_lane", None) == "fast"
        return MagicMock()
    registry.get_extractor.side_effect = check_meta
    
    orch = IngestionOrchestrator(
        registry=registry,
        classifier=MagicMock(),
        embedder=MagicMock(),
        postgres_repo=MagicMock(),
        qdrant_repo=MagicMock()
    )
    
    # Execute with octet-stream but .pdf extension.
    meta = IngestMeta(
        tenant_id="T1",
        doc_type="law",
        scope="public",
        security_level=1,
        commune_id="123",
        checksum="abc",
        mime_type="application/octet-stream",
        source_uri="http://example.com/test.pdf",
        title="test.pdf",
        pipeline_version="v1",
        ingest_lane="auto",
    )
    
    # We need to mock _call_extractor etc to avoid crashing further down
    with patch.object(orch, "_call_extractor"), \
         patch.object(orch, "_build_document"), \
         patch.object(orch, "_store_postgres"), \
         patch.object(orch, "_embed_and_upsert"):
        
        orch.process("test_file.pdf", meta)
    
    # Verify sniff was called
    mock_sniff.assert_called_once()
    mock_decide.assert_called_once()
