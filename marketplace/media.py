"""Strict validation of advertiser uploads.

Nothing a user uploads is stored as sent: images are decoded and re-encoded
(dropping metadata and any appended payload) under a random name, and videos
must be plain MP4 files whose real container headers match the required size
and length. The client-supplied file name and content type are never trusted.
"""

import io
import struct
import uuid

from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
MP4_BRANDS = {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"}
# Refuse decompression bombs before decoding any pixels.
MAX_PIXELS = 4096 * 4096


class MediaError(Exception):
    """A user-facing explanation of why a file was refused."""


def _read_all(upload, limit):
    upload.seek(0)
    data = upload.read(limit + 1)
    upload.seek(0)
    if len(data) > limit:
        raise MediaError(f"The file is larger than {limit // (1024 * 1024)} MB.")
    return data


def process_image(upload, conf):
    """Return (ContentFile, width, height) for a valid image, else raise MediaError."""
    limit = conf.image_max_mb * 1024 * 1024
    data = _read_all(upload, limit)
    try:
        probe = Image.open(io.BytesIO(data))
        fmt, (width, height) = probe.format, probe.size
        if fmt not in IMAGE_FORMATS:
            raise MediaError("Images must be JPEG, PNG or WebP.")
        if width * height > MAX_PIXELS:
            raise MediaError("The image is far too large.")
        if (width, height) != (conf.image_width, conf.image_height):
            raise MediaError(
                f"The image is {width}×{height} px; it must be exactly "
                f"{conf.image_width}×{conf.image_height} px."
            )
        if getattr(probe, "is_animated", False):
            raise MediaError("Animated images are not accepted; upload a video instead.")
        probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except MediaError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise MediaError("This file is not a valid image.")
    out = io.BytesIO()
    if fmt == "JPEG":
        image.convert("RGB").save(out, format="JPEG", quality=90, optimize=True)
    elif fmt == "PNG":
        image.save(out, format="PNG", optimize=True)
    else:
        image.save(out, format="WEBP", quality=90)
    name = f"{uuid.uuid4().hex}.{IMAGE_FORMATS[fmt]}"
    return ContentFile(out.getvalue(), name=name), width, height


def _boxes(data, start, end):
    """Yield (type, payload_start, payload_end) for the MP4 boxes in a range."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _find(data, start, end, kind):
    for box, s, e in _boxes(data, start, end):
        if box == kind:
            return s, e
    return None


def probe_mp4(data):
    """Return (width, height, seconds) of the first video track of an MP4."""
    if len(data) < 16 or data[4:8] != b"ftyp" or data[8:12] not in MP4_BRANDS:
        raise MediaError("Videos must be MP4 files (H.264).")
    moov = _find(data, 0, len(data), b"moov")
    if not moov:
        raise MediaError("This MP4 file is incomplete or damaged.")
    mvhd = _find(data, moov[0], moov[1], b"mvhd")
    if not mvhd:
        raise MediaError("This MP4 file is incomplete or damaged.")
    version = data[mvhd[0]]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", data[mvhd[0] + 20:mvhd[0] + 32])
    else:
        timescale, duration = struct.unpack(">II", data[mvhd[0] + 12:mvhd[0] + 20])
    if not timescale:
        raise MediaError("This MP4 file is incomplete or damaged.")
    seconds = duration / timescale
    for box, s, e in _boxes(data, moov[0], moov[1]):
        if box != b"trak":
            continue
        mdia = _find(data, s, e, b"mdia")
        hdlr = _find(data, *mdia, b"hdlr") if mdia else None
        if not hdlr or data[hdlr[0] + 8:hdlr[0] + 12] != b"vide":
            continue
        tkhd = _find(data, s, e, b"tkhd")
        if not tkhd:
            continue
        offset = 88 if data[tkhd[0]] == 1 else 76
        if tkhd[0] + offset + 8 > tkhd[1]:
            continue
        width, height = struct.unpack(">II", data[tkhd[0] + offset:tkhd[0] + offset + 8])
        return width >> 16, height >> 16, seconds
    raise MediaError("No video track was found in this file.")


def process_video(upload, conf):
    """Return (ContentFile, width, height, seconds) for a valid MP4, else raise MediaError."""
    limit = conf.video_max_mb * 1024 * 1024
    data = _read_all(upload, limit)
    width, height, seconds = probe_mp4(data)
    if (width, height) != (conf.video_width, conf.video_height):
        raise MediaError(
            f"The video is {width}×{height} px; it must be exactly "
            f"{conf.video_width}×{conf.video_height} px."
        )
    if not conf.video_min_seconds <= seconds <= conf.video_max_seconds + 0.5:
        raise MediaError(
            f"The video is {seconds:.0f} s long; it must be between "
            f"{conf.video_min_seconds} and {conf.video_max_seconds} seconds."
        )
    return ContentFile(data, name=f"{uuid.uuid4().hex}.mp4"), width, height, round(seconds)
