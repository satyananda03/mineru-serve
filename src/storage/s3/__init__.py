"""S3 for the parser service: hosting of figure crops."""

from .objects import delete_object, require_bucket, upload_fileobj, upload_figures_to_s3

__all__ = ["delete_object", "require_bucket", "upload_fileobj", "upload_figures_to_s3"]
