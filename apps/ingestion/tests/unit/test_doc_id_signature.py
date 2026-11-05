import pytest
import uuid
from app.preproc.utils.ids import make_doc_id

class TestDocIdSignature:
    def test_make_doc_id_signature(self):
        """Should accept commune_id and be deterministic"""
        # Orchestrator-like call
        uid1 = make_doc_id(
            tenant_id="t1",
            scope="public",
            doc_type="law",
            checksum="abc",
            commune_id="HANOI"
        )
        assert isinstance(uid1, uuid.UUID)

        # Confirm determinism
        uid2 = make_doc_id(
            tenant_id="t1",
            scope="public",
            doc_type="law",
            checksum="abc",
            commune_id="HANOI"
        )
        assert uid1 == uid2

        # Confirm sensitvity to commune_id
        uid3 = make_doc_id(
            tenant_id="t1",
            scope="public",
            doc_type="law",
            checksum="abc",
            commune_id="HCM"
        )
        assert uid1 != uid3
