import io

from PIL import Image


def _create_test_image(width: int = 2000, height: int = 1500, fmt: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


async def test_process_photo_creates_variants() -> None:
    from app.media.processing import process_photo

    original = _create_test_image(2000, 1500)
    variant_specs: list[dict[str, int | str]] = [
        {"name": "large", "max_width": 1200, "quality": 85},
        {"name": "medium", "max_width": 600, "quality": 80},
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    assert len(results) == 3
    for spec in variant_specs:
        name = str(spec["name"])
        assert name in results
        img = Image.open(io.BytesIO(results[name]))
        assert img.format == "WEBP"
        assert img.width <= int(spec["max_width"])


async def test_process_photo_does_not_upscale() -> None:
    from app.media.processing import process_photo

    original = _create_test_image(100, 75)
    variant_specs: list[dict[str, int | str]] = [
        {"name": "large", "max_width": 1200, "quality": 85},
        {"name": "small", "max_width": 200, "quality": 75},
    ]

    results = process_photo(original, variant_specs)

    for name in results:
        img = Image.open(io.BytesIO(results[name]))
        assert img.width <= 100


async def test_process_photo_strips_exif() -> None:
    from app.media.processing import process_photo

    img = Image.new("RGB", (800, 600), color="blue")
    from PIL.ExifTags import Base as ExifBase

    exif_data = img.getexif()
    exif_data[ExifBase.Make] = "TestCamera"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_data.tobytes())
    original = buf.getvalue()

    results = process_photo(original, [{"name": "medium", "max_width": 600, "quality": 80}])

    result_img = Image.open(io.BytesIO(results["medium"]))
    result_exif = result_img.getexif()
    assert ExifBase.Make not in result_exif
