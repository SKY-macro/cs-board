#!/usr/bin/env python3
"""Render a story page as text -> aligned B/W plate -> color plate reveals.

This renderer intentionally shares no stroke tracing, hand, pen-tip, or drawing
logic with the whiteboard renderer.  It reproduces the flat layer wipes used by
the supplied diary-comic reference video.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stream_render as sr  # noqa: E402


def ease(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return 0.5 - 0.5 * math.cos(math.pi * progress)


def scaled_rect(region: dict, sx: float, sy: float, width: int, height: int) -> tuple[int, int, int, int]:
    x0 = max(0, min(width, round(float(region["x"]) * sx)))
    y0 = max(0, min(height, round(float(region["y"]) * sy)))
    x1 = max(0, min(width, round((float(region["x"]) + float(region["width"])) * sx)))
    y1 = max(0, min(height, round((float(region["y"]) + float(region["height"])) * sy)))
    return x0, y0, x1, y1


def handwriting_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/STXINGKA.TTF"),
        Path("C:/Windows/Fonts/STKAITI.TTF"),
        Path("C:/Windows/Fonts/simkai.ttf"),
        Path("/System/Library/Fonts/STKaiti.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    font_path = next((path for path in candidates if path.exists()), None)
    return ImageFont.truetype(str(font_path), size) if font_path else ImageFont.load_default()


def wrapped_lines(text: str, max_chars: int) -> list[str]:
    compact = "".join(str(text).split())
    return [compact[index:index + max_chars] for index in range(0, len(compact), max_chars)] or [""]


def caption_plate(annotation: dict, width: int, height: int, sx: float, sy: float) -> np.ndarray:
    plate = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    for element in annotation["elements"]:
        region = element.get("captionRegion") or element["region"]
        x0, y0, x1, y1 = scaled_rect(region, sx, sy, width, height)
        region_width, region_height = max(1, x1 - x0), max(1, y1 - y0)
        text = str(element.get("subtitle") or "").strip()
        font_size = max(22, min(round(height * 0.055), round(region_height * 0.30)))
        while font_size > 22:
            max_chars = max(4, int(region_width / (font_size * 1.02)))
            if len(wrapped_lines(text, max_chars)) * font_size * 1.28 <= region_height:
                break
            font_size -= 2
        font = handwriting_font(font_size)
        max_chars = max(4, int(region_width / (font_size * 1.02)))
        draw.multiline_text(
            (x0 + max(8, round(region_width * 0.04)), y0 + max(4, round(region_height * 0.04))),
            "\n".join(wrapped_lines(text, max_chars)), font=font, fill=(23, 23, 20, 255),
            spacing=max(3, font_size // 5), stroke_width=max(0, font_size // 42), stroke_fill=(23, 23, 20, 255),
        )
    return cv2.cvtColor(np.asarray(plate), cv2.COLOR_RGBA2BGRA)


def line_plate(color: np.ndarray, canvas: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    threshold = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 10)
    threshold = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    lines = np.repeat(threshold[:, :, None], 3, axis=2)
    ink = threshold < 245
    result = canvas.copy()
    result[ink] = lines[ink]
    return result


def overlay_bgra(frame: np.ndarray, layer: np.ndarray, mask: np.ndarray) -> None:
    alpha = (layer[:, :, 3].astype(np.float32) / 255.0) * mask.astype(np.float32)
    frame[:] = frame * (1.0 - alpha[:, :, None]) + layer[:, :, :3] * alpha[:, :, None]


def reveal_mask(width: int, height: int, rect: tuple[int, int, int, int], progress: float) -> np.ndarray:
    x0, y0, x1, y1 = rect
    mask = np.zeros((height, width), dtype=bool)
    edge = x0 + round((x1 - x0) * ease(progress))
    mask[y0:y1, x0:max(x0, edge)] = True
    return mask


def render(image_path: Path, annotation_path: Path, output_path: Path, fps: int = 30, output_width: int = 1080, output_height: int = 1440) -> Path:
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    source = sr._imread_any(image_path)
    if source is None:
        raise RuntimeError(f"无法读取图片：{image_path}")
    width = max(2, round(output_width) // 2 * 2)
    height = max(2, round(output_height) // 2 * 2)
    color = cv2.resize(source, (width, height), interpolation=cv2.INTER_AREA)
    corner = np.concatenate([color[:8, :8].reshape(-1, 3), color[-8:, -8:].reshape(-1, 3)])
    background = np.median(corner, axis=0).astype(np.uint8)
    canvas = np.empty_like(color)
    canvas[...] = background
    bw = line_plate(color, canvas)
    sx = width / float(annotation["canvas"]["width"])
    sy = height / float(annotation["canvas"]["height"])
    captions = caption_plate(annotation, width, height, sx, sy)
    duration_ms = int(annotation["sceneDurationMs"])
    total_frames = max(1, round(duration_ms * fps / 1000))
    raw_path = output_path.with_name(output_path.stem + "_raw.mp4")
    writer = cv2.VideoWriter(str(raw_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("无法打开故事绘本视频写入器")
    try:
        for frame_index in range(total_frames):
            now_ms = frame_index * 1000.0 / fps
            frame = canvas.astype(np.float32)
            for element in annotation["elements"]:
                start = float(element["reveal"]["startMs"])
                duration = max(1.0, float(element["reveal"]["durationMs"]))
                local = (now_ms - start) / duration
                if local < 0:
                    continue
                caption_rect = scaled_rect(element.get("captionRegion") or element["region"], sx, sy, width, height)
                art_rect = scaled_rect(element["region"], sx, sy, width, height)
                overlay_bgra(frame, captions, reveal_mask(width, height, caption_rect, local / 0.22))
                bw_progress = (local - 0.18) / 0.40
                bw_mask = reveal_mask(width, height, art_rect, bw_progress)
                frame[bw_mask] = bw[bw_mask]
                color_progress = (local - 0.52) / 0.36
                color_mask = reveal_mask(width, height, art_rect, color_progress)
                frame[color_mask] = color[color_mask]
            writer.write(np.clip(frame, 0, 255).astype(np.uint8))
    finally:
        writer.release()
    final = sr.transcode_h264(raw_path, output_path)
    raw_path.unlink(missing_ok=True)
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description="故事绘本分层揭示：文字 → 黑白线稿 → 彩色插画")
    parser.add_argument("image")
    parser.add_argument("annotation")
    parser.add_argument("output")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1440)
    args = parser.parse_args()
    final = render(Path(args.image), Path(args.annotation), Path(args.output), args.fps, args.width, args.height)
    print(f"OUTPUT={final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
