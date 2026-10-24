"""Mandatory private research archive, immutable generation-precondition writes."""
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage

from .storage import IntegrityError
from .study_config import canonical


class GCSArchive:
    durable = True

    def __init__(self, bucket, client=None):
        self.client = client if client is not None else storage.Client()
        self.bucket = self.client.bucket(bucket)

    def put(self, name, value):
        content = canonical(value)
        blob = self.bucket.blob(name)
        try:
            blob.upload_from_string(content, content_type="application/json", if_generation_match=0,
                                    checksum="crc32c", timeout=30)
        except PreconditionFailed:
            # Pin the read generation as well, so a replaced object cannot race this comparison.
            blob.reload(timeout=15)
            existing = blob.download_as_bytes(if_generation_match=int(blob.generation), checksum="crc32c", timeout=30)
            if existing != content:
                raise IntegrityError("immutable GCS object differs from accepted record")

    def probe(self):
        self.bucket.reload(timeout=15)
        iam = self.bucket.iam_configuration
        if not iam.uniform_bucket_level_access_enabled or iam.public_access_prevention != "enforced":
            raise RuntimeError("research bucket requires uniform access and enforced public access prevention")
        # Prove create/read access without writing participant data or changing existing objects.
        self.put("readiness/schema-v1.json", {"schema_version": "1", "purpose": "readiness"})
