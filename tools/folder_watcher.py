import os
import time
import shutil
import logging
import hashlib
import yaml
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("FolderWatcher")

def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def calculate_checksum(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return f"sha256:{sha256_hash.hexdigest()}"

def get_file_size(file_path: Path) -> int:
    return file_path.stat().st_size

def wait_for_stability(file_path: Path, wait_seconds: int = 2) -> bool:
    """Ensure file is not currently being written to."""
    size_1 = get_file_size(file_path)
    time.sleep(wait_seconds)
    size_2 = get_file_size(file_path)
    return size_1 == size_2

def move_file(file_path: Path, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Handle duplicates by appending timestamp if needed
    dest_path = dest_dir / file_path.name
    if dest_path.exists():
         timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
         dest_path = dest_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
    
    shutil.move(str(file_path), str(dest_path))
    logger.info(f"Moved {file_path.name} -> {dest_path}")

def process_file(file_path: Path, profile_id: str, config: Dict[str, Any]) -> bool:
    api_url = config['api_url']
    headers = {
        "X-GOVAI-TENANT-ID": config['auth']['tenant_id'],
        "X-GOVAI-USER-ROLE": config['auth']['user_role']
    }
    
    try:
        size = get_file_size(file_path)
        mime = "application/octet-stream" # Fallback, or assume extensions
        if file_path.suffix.lower() == ".pdf":
            mime = "application/pdf"
        elif file_path.suffix.lower() in [".docx", ".doc"]:
             mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        # 1. Presign
        logger.info(f"Requesting presigned URL for {file_path.name}...")
        resp = requests.post(
            f"{api_url}/admin/upload/presign",
            json={
                "profile_id": profile_id,
                "filename": file_path.name,
                "mime_type": mime,
                "size_bytes": size
            },
            headers=headers
        )
        if resp.status_code != 200:
            logger.error(f"Presign failed: {resp.text}")
            return False
            
        presign_data = resp.json()
        upload_url = presign_data['upload_url']
        object_key = presign_data['object_key']
        
        # 2. Upload to S3
        logger.info(f"Uploading content to S3...")
        with open(file_path, 'rb') as f:
            put_resp = requests.put(upload_url, data=f, headers={"Content-Type": mime})
            
        if put_resp.status_code not in [200, 204]:
             logger.error(f"S3 Upload failed: {put_resp.status_code} {put_resp.text}")
             return False

        # 3. Submit Job
        logger.info(f"Submitting Job...")
        checksum = calculate_checksum(file_path)
        job_payload = {
            "profile_id": profile_id,
            "files": [{
                "object_key": object_key,
                "original_name": file_path.name,
                "mime_type": mime,
                "size_bytes": size,
                "checksum": checksum
            }],
            "note": "Auto-ingested by FolderWatcher"
        }
        
        job_resp = requests.post(f"{api_url}/admin/jobs", json=job_payload, headers=headers)
        if job_resp.status_code != 200:
            logger.error(f"Job Submission failed: {job_resp.text}")
            return False
            
        data = job_resp.json()
        logger.info(f"SUCCESS: Created {data['jobs_created']} job(s). Status: {data['status']}")
        return True

    except Exception as e:
        logger.exception(f"Unexpected error processing {file_path.name}")
        return False

def fetch_remote_config(server_id: str, config: Dict[str, Any]) -> list:
    api_url = config['api_url']
    headers = {
        "X-GOVAI-TENANT-ID": config['auth']['tenant_id'],
        "X-GOVAI-USER-ROLE": "admin"
    }
    try:
        resp = requests.get(
            f"{api_url}/admin/sources/config?server_id={server_id}",
            headers=headers,
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('bindings', [])
        else:
            logger.warning(f"Config poll failed: {resp.status_code} {resp.text}")
            return []
    except Exception as e:
        logger.error(f"Config poll error: {e}")
        return []

def main():
    config_path = "tools/watcher_config.yaml"
    if not os.path.exists(config_path):
        logger.error(f"Config not found: {config_path}")
        return

    config = load_config(config_path)
    server_id = config.get('server_id', 'DEFAULT_SERVER')
    logger.info(f"FolderWatcher v2 started. Server ID: {server_id}")
    
    # Initial Config Strategy: Local + Remote
    # We will prioritize Remote.
    
    while True:
        try:
            # 1. Poll Config
            remote_bindings = fetch_remote_config(server_id, config)
            
            active_monitors = []
            if remote_bindings:
                active_monitors = remote_bindings
                logger.info(f"Synced {len(active_monitors)} bindings from API.")
            else:
                # Fallback to local if remote empty/failed?
                # For Pilot P1, let's allow fallback to local monitors if defined
                # to support "legacy" mode until migration is full.
                active_monitors = config.get('monitors', [])
                if active_monitors:
                   logger.info(f"Using {len(active_monitors)} local monitors (Fallback).")

            # 2. Process Monitors
            for monitor in active_monitors:
                monitor_path = Path(monitor['path'])
                profile_id = monitor['profile_id']
                
                if not monitor_path.exists():
                    # Create if not exists for testing convenience
                    try:
                        monitor_path.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        logger.error(f"Cannot create path {monitor_path}: {e}")
                        continue
                
                # Scan files
                # Use list to avoid iterator issues if files move
                files = list(monitor_path.glob("*"))
                
                for file_path in files:
                    if file_path.is_file() and not file_path.name.startswith("."):
                        logger.info(f"Detected file: {file_path.name} in {monitor_path}")
                        
                        if wait_for_stability(file_path, config.get('stability_wait', 2)):
                            success = process_file(file_path, profile_id, config)
                            
                            date_str = datetime.now().strftime("%Y-%m-%d")
                            processed_root = Path(config.get('processed_dir', 'data/processed'))
                            failed_root = Path(config.get('failed_dir', 'data/failed'))
                            
                            if success:
                                dest = processed_root / date_str
                                move_file(file_path, dest)
                            else:
                                dest = failed_root / date_str
                                move_file(file_path, dest)
                        else:
                            logger.warning(f"File {file_path.name} is unstable, skipping.")
                            
            time.sleep(config.get('polling_interval', 30))
            
        except KeyboardInterrupt:
            logger.info("Stopping FolderWatcher...")
            break
        except Exception as e:
            logger.exception("Global Loop Error")
            time.sleep(10)

if __name__ == "__main__":
    main()
