"""P2: read text aloud (OCR with EasyOCR) from camera.latest_frame().

Lines are returned with the biggest text first, then the rest top to bottom.
EasyOCR is loaded once, on first use.
"""
from __future__ import annotations

import threading
from typing import List, Optional, Sequence, Tuple

MAX_LINES = 5
MIN_CONFIDENCE = 0.3
NO_TEXT = "No readable text — try moving closer."

_reader = None
_reader_lock = threading.Lock()


def read_text(frame=None) -> str:
    if frame is None:
        from .camera import camera
        frame = camera.latest_frame()
    if frame is None:
        return "Camera not available."
    ocr = _get_reader()
    if ocr is None:
        return "Text reading is not installed."
    with _reader_lock:
        results = ocr.readtext(frame)
    lines = order_lines(results)
    return ". ".join(lines[:MAX_LINES]) if lines else NO_TEXT


def order_lines(results: Sequence[Tuple[Sequence[Sequence[float]], str, float]]) -> List[str]:
    """Groups EasyOCR (box, text, conf) results into lines; biggest line first, then top to bottom."""
    words = []
    for box, text, conf in results:
        text = text.strip()
        if not text or conf < MIN_CONFIDENCE:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        words.append({"text": text, "top": min(ys), "bottom": max(ys), "left": min(xs)})
    if not words:
        return []

    words.sort(key=lambda w: (w["top"] + w["bottom"]) / 2)
    lines: List[List[dict]] = []
    for word in words:
        centre = (word["top"] + word["bottom"]) / 2
        if lines:
            last = lines[-1]
            top = min(w["top"] for w in last)
            bottom = max(w["bottom"] for w in last)
            if top <= centre <= bottom:
                last.append(word)
                continue
        lines.append([word])

    def height(line: List[dict]) -> float:
        return max(w["bottom"] - w["top"] for w in line)

    texts = [" ".join(w["text"] for w in sorted(line, key=lambda w: w["left"])) for line in lines]
    biggest = max(range(len(lines)), key=lambda i: height(lines[i]))
    return [texts[biggest]] + [t for i, t in enumerate(texts) if i != biggest]


def _get_reader() -> Optional[object]:
    global _reader
    with _reader_lock:
        if _reader is None:
            try:
                import easyocr
            except ImportError:
                return None
            _reader = easyocr.Reader(["en"], gpu=False)
        return _reader


if __name__ == "__main__":
    import sys

    import cv2

    image = cv2.imread(sys.argv[1])
    if image is None:
        sys.exit(f"could not read {sys.argv[1]}")
    print(read_text(image))
