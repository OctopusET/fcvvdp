"""Deterministic image/video inputs, generated with the Python standard library."""

import struct
import zlib
from pathlib import Path


def pixels(width, height, distorted=False, frame=0):
    data = bytearray()
    for y in range(height):
        for x in range(width):
            for c in range(3):
                value = (x * (3 + c) + y * (7 - c) + frame * 11 + c * 53) % 256
                if distorted:
                    value = min(255, max(0, value + ((x + y + c + frame) % 13 - 6)))
                data.append(value)
    return bytes(data)


def png(path, width, height, rgb, color=2, depth=8):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG filter: none
        for x in range(width):
            offset = (y * width + x) * 3
            p = rgb[offset:offset + 3]
            samples = list(p if color in (2, 6) else p[:1])
            if color in (4, 6):
                samples.append((x * 17 + y * 31) % 256)
            assert len(samples) == channels
            for value in samples:
                raw.extend(bytes([value]) if depth == 8 else struct.pack(">H", value * 257))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def y4m(path, width, height, frames=5, bits=8, chroma="420jpeg", full=False,
        distorted=False):
    header = (f"YUV4MPEG2 W{width} H{height} F30000:1001 Ip A1:1 C{chroma}"
              f" XCOLORRANGE={'FULL' if full else 'LIMITED'}\n")
    peak = (1 << bits) - 1
    scale = 1 << (bits - 8)
    with path.open("wb") as out:
        out.write(header.encode())
        for frame in range(frames):
            out.write(b"FRAME\n")
            for plane in range(3):
                w, h = (width, height) if plane == 0 else ((width + 1) // 2, (height + 1) // 2)
                values = bytearray()
                for y in range(h):
                    for x in range(w):
                        value = (16 + (x * 3 + y * 5 + frame * 11) % 220 if plane == 0
                                 else 96 + (x * 7 + y * 3 + plane * 17 + frame * 2) % 65)
                        value = value * scale + ((x + y + frame) % scale)
                        if distorted:
                            value += ((x + y + plane + frame) % 7 - 3) * scale
                        value = min(peak, max(0, value))
                        values.extend(bytes([value]) if bits == 8 else struct.pack("<H", value))
                out.write(values)


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    width, height = 65, 49
    for label, distorted in (("ref", False), ("dis", True)):
        rgb = pixels(width, height, distorted)
        gray = rgb[::3]
        for color in (0, 2, 4, 6):
            for depth in (8, 16):
                png(directory / f"{label}-png{color}-{depth}.png", width, height, rgb, color, depth)
        qoi = bytearray(b"qoif" + struct.pack(">IIBB", width, height, 3, 0))
        for i in range(0, len(rgb), 3):
            qoi.extend(b"\xfe" + rgb[i:i + 3])
        qoi.extend(b"\0\0\0\0\0\0\0\1")
        (directory / f"{label}.qoi").write_bytes(qoi)
        rgba_qoi = bytearray(b"qoif" + struct.pack(">IIBB", width, height, 4, 0))
        for i in range(width * height):
            rgba_qoi.extend(b"\xff" + rgb[i * 3:i * 3 + 3] + bytes([(i * 17) % 256]))
        rgba_qoi.extend(b"\0\0\0\0\0\0\0\1")
        (directory / f"{label}-rgba.qoi").write_bytes(rgba_qoi)
        bitmap = [int(v < 128) for v in gray]
        (directory / f"{label}-P1.pbm").write_bytes(
            f"P1\n{width} {height}\n".encode() + " ".join(map(str, bitmap)).encode())
        packed = bytearray()
        for y in range(height):
            for x in range(0, width, 8):
                packed.append(sum(bitmap[y * width + x + b] << (7 - b)
                                  for b in range(min(8, width - x))))
        (directory / f"{label}-P4.pbm").write_bytes(f"P4\n{width} {height}\n".encode() + packed)
        for magic, ext, channels in (("P2", "pgm", 1), ("P3", "ppm", 3),
                                     ("P5", "pgm", 1), ("P6", "ppm", 3)):
            data = gray if channels == 1 else rgb
            for maximum in (255, 1023, 65535):
                samples = [v * maximum // 255 for v in data]
                payload = (" ".join(map(str, samples)).encode() if magic in ("P2", "P3")
                           else bytes(samples) if maximum == 255
                           else b"".join(struct.pack(">H", v) for v in samples))
                (directory / f"{label}-{magic}-{maximum}.{ext}").write_bytes(
                    f"{magic}\n# regression fixture\n{width} {height}\n{maximum}\n".encode() + payload)
        for channels, kind in ((1, "GRAYSCALE"), (2, "GRAYSCALE_ALPHA"), (3, "RGB"), (4, "RGB_ALPHA")):
            data = bytearray()
            for i in range(width * height):
                data.extend(rgb[i * 3:i * 3 + 3] if channels >= 3 else gray[i:i + 1])
                if channels in (2, 4):
                    data.append((i * 17) % 256)
            (directory / f"{label}-{channels}.pam").write_bytes(
                f"P7\nWIDTH {width}\nHEIGHT {height}\nDEPTH {channels}\nMAXVAL 255\nTUPLTYPE {kind}\nENDHDR\n".encode() + data)
        for bits, chroma in ((8, "420jpeg"), (8, "420mpeg2"), (8, "420paldv"),
                             (9, "420p9"), (10, "420p10"), (12, "420p12"), (16, "420p16")):
            for full in (False, True):
                y4m(directory / f"{label}-{chroma}-{full}.y4m", 65, 49,
                    bits=bits, chroma=chroma, full=full, distorted=distorted)
    png(directory / "wrong-size.png", 64, 48, pixels(64, 48))
    y4m(directory / "short.y4m", 65, 49, frames=1)
    y4m(directory / "empty.y4m", 65, 49, frames=0)
    (directory / "bad.png").write_bytes(b"not a png")
    (directory / "bad.ppm").write_bytes(b"P6\n65 49\n255\n\0")
    return directory
