import io

from PIL import Image, ImageOps


def process_photo(original_data: bytes, variant_specs: list[dict[str, int | str]]) -> dict[str, bytes]:
    base: Image.Image = Image.open(io.BytesIO(original_data))
    transposed = ImageOps.exif_transpose(base)
    img: Image.Image = transposed if transposed is not None else base

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    results: dict[str, bytes] = {}
    for spec in variant_specs:
        name = str(spec["name"])
        max_width = int(spec["max_width"])
        quality = int(spec["quality"])

        variant: Image.Image = img.copy()
        if variant.width > max_width:
            ratio = max_width / variant.width
            new_height = int(variant.height * ratio)
            variant = variant.resize((max_width, new_height), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        variant.save(buf, format="WEBP", quality=quality)
        results[name] = buf.getvalue()

    return results
