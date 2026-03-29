import os

from app.core.config import Settings


def test_storage_settings_loaded() -> None:
    os.environ["APP_ENV"] = "test"
    settings = Settings()
    assert settings.storage.endpoint_url == "http://localhost:9002"
    assert settings.storage.bucket == "rental-media-test"
    assert settings.storage.presigned_url_expiry_seconds == 3600


def test_media_settings_loaded() -> None:
    os.environ["APP_ENV"] = "test"
    settings = Settings()
    assert settings.media.max_photo_size_mb == 20
    assert settings.media.orphan_cleanup_after_hours == 24
    assert "profile" in settings.media.photo_variant_sets
    assert "listing" in settings.media.photo_variant_sets
    profile_variants = settings.media.photo_variant_sets["profile"]
    assert len(profile_variants) == 2
    assert profile_variants[0]["name"] == "medium"


def test_worker_settings_loaded() -> None:
    os.environ["APP_ENV"] = "test"
    settings = Settings()
    assert settings.worker.redis_url == "redis://localhost:6380"
    assert settings.worker.max_concurrent_jobs == 10
