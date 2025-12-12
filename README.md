# PDF Rect Picker

PyQt6 + PyMuPDF desktop app for drawing rectangles on top of a PDF page and reading their PyMuPDF `fitz.Rect` coordinates. Supports zooming, scrolling, clipboard copy, and JSON output for the current selection.

## Requirements

- Python 3.10+
- PyMuPDF
- PyQt6

Install deps (in a virtualenv is recommended):

```bash
pip install -r requirements.txt
```

## Run

```bash
python pdf_rect_picker.py
```

## Features

- Open a PDF and render pages via PyMuPDF pixmaps.
- Scrollable viewport with zoom in/out/reset.
- Drag to select with a rubber-band rectangle; Esc clears the selection.
- Shows `Rect`, width/height, page info, and JSON payload; copies `fitz.Rect(...)` to the clipboard.

## Shortcuts

- Zoom in/out: standard Ctrl+Plus / Ctrl+Minus
- Reset zoom: Ctrl+0
- Copy rect: Ctrl+C
- Clear selection: Esc

## Notes

- Coordinates follow PyMuPDF's origin (top-left, y increases downward) and clamp to the page bounds.
- Selection stays aligned when zooming the same page; changing pages clears the selection.
