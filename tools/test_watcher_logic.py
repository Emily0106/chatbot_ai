import os
import shutil
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from tools.folder_watcher import process_file, wait_for_stability

# Test Data
TEST_FILE = Path("test_doc.pdf")
CONFIG = {
    "api_url": "http://mock-api",
    "auth": {"tenant_id": "cust1", "user_role": "admin"},
    "processed_dir": "processed",
    "failed_dir": "failed"
}

@pytest.fixture
def setup_file():
    TEST_FILE.write_bytes(b"dummy content")
    yield TEST_FILE
    if TEST_FILE.exists():
        TEST_FILE.unlink()

def test_process_file_success(setup_file):
    with patch("requests.post") as mock_post, \
         patch("requests.put") as mock_put:
        
        # 1. Presign Response
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {
                "upload_url": "http://s3/put", 
                "object_key": "raw/key"
            }),
            # 3. Job Submit Response
            MagicMock(status_code=200, json=lambda: {
                "jobs_created": 1, 
                "status": "queued"
            })
        ]
        
        # 2. S3 Put Response
        mock_put.return_value.status_code = 200
        
        success = process_file(TEST_FILE, "profile_123", CONFIG)
        
        assert success is True
        assert mock_post.call_count == 2
        assert mock_put.call_count == 1

def test_process_file_failure(setup_file):
    with patch("requests.post") as mock_post:
        # Presign fails
        mock_post.return_value.status_code = 500
        
        success = process_file(TEST_FILE, "profile_123", CONFIG)
        
        assert success is False
