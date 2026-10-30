"""Single-threaded HEIF conversion inside the bounded decoder subprocess."""

import io
import sys
import pillow_heif
from PIL import Image, ImageOps, ImageCms


def main():
    source, level, target = sys.argv[1:]
    level = int(level)
    if level not in (64, 256, 512, 1024, 2048):
        raise ValueError("Invalid preview size")
    pillow_heif.register_heif_opener(
        decode_threads=1, depth_images=False, aux_images=False
    )
    Image.MAX_IMAGE_PIXELS = 150_000_000
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original)
        profile = image.info.get("icc_profile")
        if profile:
            image = ImageCms.profileToProfile(
                image,
                ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                ImageCms.createProfile("sRGB"),
                outputMode="RGBA" if image.mode == "RGBA" else "RGB",
            )
        image.thumbnail((level, level), Image.Resampling.LANCZOS)
        image.info.clear()
        image.save(target, "WEBP", quality=80, exif=b"", icc_profile=b"", xmp=b"")


if __name__ == "__main__":
    main()
