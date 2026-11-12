"""Cek upload figure ke S3 dengan client palsu (tanpa jaringan).

Jalankan dari root repo: ``python tests/test_s3_upload.py`` (atau ``pytest tests``).
"""
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage.s3 import objects


class FakeS3:
    def __init__(self, fail_on: str | None = None):
        self.uploaded: dict[str, dict] = {}
        self.fail_on = fail_on

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        if self.fail_on and key.endswith(self.fail_on):
            raise ConnectionError("jaringan putus")
        self.uploaded[key] = {"bucket": bucket, "bytes": fileobj.read(), **ExtraArgs}


def with_fake_s3(check, fail_on: str | None = None):
    """Jalankan ``check(fake, figure_paths)`` dengan settings S3 uji dan client palsu."""
    original_settings, original_client = objects.settings, objects.get_client
    fake = FakeS3(fail_on)
    objects.settings = replace(original_settings, s3_bucket="bucket-uji", s3_region="ap-southeast-1", s3_prefix="/figur/")
    objects.get_client = lambda: fake
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = []
            for name in ("a.jpg", "b.png"):
                path = Path(tmp_dir) / name
                path.write_bytes(name.encode())
                paths.append(str(path))
            check(fake, paths)
    finally:
        objects.settings, objects.get_client = original_settings, original_client


def test_figures_are_uploaded_and_img_path_becomes_their_url():
    def check(fake, paths):
        items = [{"type": "image", "img_path": path} for path in paths]
        objects.upload_figures_to_s3(items)
        assert len(fake.uploaded) == 2
        for item, path in zip(items, paths):
            prefix = "https://bucket-uji.s3.ap-southeast-1.amazonaws.com/"
            assert item["img_path"].startswith(prefix + "figur/") and item["img_path"].endswith(Path(path).suffix)
            stored = fake.uploaded[item["img_path"].removeprefix(prefix)]
            assert stored["bucket"] == "bucket-uji" and stored["bytes"] == Path(path).name.encode()
        assert {stored["ContentType"] for stored in fake.uploaded.values()} == {"image/jpeg", "image/png"}

    with_fake_s3(check)


def test_one_failed_upload_leaves_every_img_path_local():
    def check(fake, paths):
        items = [{"type": "image", "img_path": path} for path in paths]
        try:
            objects.upload_figures_to_s3(items)
        except RuntimeError as error:
            assert "b.png" in str(error)
        else:
            raise AssertionError("upload yang gagal harus melempar error")
        assert [item["img_path"] for item in items] == paths

    with_fake_s3(check, fail_on=".png")


def test_missing_bucket_is_a_clear_error_and_no_figures_needs_no_s3():
    original = objects.settings
    objects.settings = replace(original, s3_bucket=None)
    try:
        objects.upload_figures_to_s3([])  # dokumen tanpa figure tidak butuh S3
        try:
            objects.require_bucket()
        except ValueError as error:
            assert "S3_BUCKET" in str(error)
        else:
            raise AssertionError("bucket kosong harus melempar ValueError")
    finally:
        objects.settings = original


if __name__ == "__main__":
    tests = [check for name, check in list(globals().items()) if name.startswith("test_")]
    for check in tests:
        check()
        print("ok", check.__name__)
    print(f"{len(tests)} cek lolos")
