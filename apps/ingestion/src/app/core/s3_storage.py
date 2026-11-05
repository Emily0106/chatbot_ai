import os
import datetime
import hashlib
import hmac
from urllib.parse import quote

class S3Signer:
    """
    Minimal AWS Signature Version 4 implementation for Presigned URLs.
    Zero-dependency (only stdlib).
    """
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str = "us-east-1"):
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region

    def _sign(self, key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def _get_signature_key(self, key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
        k_date = self._sign(("AWS4" + key).encode("utf-8"), date_stamp)
        k_region = self._sign(k_date, region_name)
        k_service = self._sign(k_region, service_name)
        k_signing = self._sign(k_service, "aws4_request")
        return k_signing

    def generate_presigned_put(self, object_key: str, expires_in: int = 3600, content_type: str = "application/octet-stream") -> str:
        """
        Generates a Presigned PUT URL.
        """
        method = "PUT"
        service = "s3"
        host = self.endpoint.replace("http://", "").replace("https://", "")
        
        # MinIO/S3 Path
        # If path-style: http://host/bucket/key
        # If virtual-host: http://bucket.host/key
        # We assume Path-Style for local MinIO typically.
        # Check if endpoint includes bucket? No.
        
        uri_path = f"/{self.bucket}/{object_key}"
        
        t = datetime.datetime.utcnow()
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = t.strftime("%Y%m%d")

        canonical_uri = uri_path
        canonical_querystring = (
            f"X-Amz-Algorithm=AWS4-HMAC-SHA256&"
            f"X-Amz-Credential={quote(self.access_key, safe='')}%2F{date_stamp}%2F{self.region}%2F{service}%2Faws4_request&"
            f"X-Amz-Date={amz_date}&"
            f"X-Amz-Expires={expires_in}&"
            f"X-Amz-SignedHeaders=host"
        )
        
        canonical_headers = f"host:{host}\n"
        signed_headers = "host"
        payload_hash = "UNSIGNED-PAYLOAD"
        
        canonical_request = (
            f"{method}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )
        
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.region}/{service}/aws4_request"
        string_to_sign = (
            f"{algorithm}\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        
        signing_key = self._get_signature_key(self.secret_key, date_stamp, self.region, service)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        
        return f"{self.endpoint}{canonical_uri}?{canonical_querystring}&X-Amz-Signature={signature}"

# Global instance factory
def get_s3_signer() -> S3Signer:
    # Env vars
    endpoint = os.getenv("S3_ENDPOINT", os.getenv("QDRANT_URL", "http://minio:9000")) # Fallback hack? No.
    # In dev.env we don't have S3 vars!
    # I need to add defaults or check if Minio is even running.
    # If S3 is not configured, we might have to use local file system presign simulation (fake)?
    # User requested "Presigned Upload", implying S3.
    # I will default to localhost MinIO for now.
    
    endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
    access = os.getenv("S3_ACCESS_KEY", "minioadmin")
    secret = os.getenv("S3_SECRET_KEY", "minioadmin")
    bucket = os.getenv("S3_BUCKET", "ingestion")
    
    return S3Signer(endpoint, access, secret, bucket)
