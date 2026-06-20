import logging
import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )
        self.bucket = settings.S3_BUCKET

    def upload_file(self, key: str, file_obj) -> None:
        try:
            self.client.upload_fileobj(file_obj, self.bucket, key)
            logger.info(f"✅ Uploaded S3: {key}")
        except Exception as e:
            logger.error(f"❌ Failed to upload S3 {key}: {str(e)}", exc_info=True)
            raise

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def download_file(self, key: str, dest_path: str) -> None:
        self.client.download_file(self.bucket, key, dest_path)

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        if settings.S3_PUBLIC_ENDPOINT:
            url = url.replace(settings.S3_ENDPOINT, settings.S3_PUBLIC_ENDPOINT, 1)
        return url

    def delete_file(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_files(self, keys: list[str]) -> None:
        if not keys:
            return
        objects = [{"Key": k} for k in keys]
        self.client.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": objects},
        )

    def file_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


storage = StorageService()
