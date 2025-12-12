import sys
import json
from pathlib import Path

import fitz  # PyMuPDF
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal, QSize
from PyQt6.QtGui import QGuiApplication, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QRubberBand,
    QPlainTextEdit,
)


class ScrollAreaWithSignal(QScrollArea):
    """Scroll area that notifies on viewport resize so the viewer can adjust."""

    viewport_resized = pyqtSignal(QSize)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_resized.emit(self.viewport().size())


class PdfViewerWidget(QWidget):
    """Widget that renders a PDF page pixmap and handles rubber band selection."""

    selection_changed = pyqtSignal(object)  # Emits fitz.Rect or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: QPixmap | None = None
        self.page_rect: fitz.Rect | None = None
        self.scale_factor: float = 1.0
        self._pdf_selection: fitz.Rect | None = None
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._dragging = False
        self._drag_start = QPoint()
        self._selection_widget_rect: QRectF | None = None
        self._viewport_size = QSize()
        self.setMouseTracking(True)

    def set_viewport_size(self, size: QSize) -> None:
        self._viewport_size = size
        self._update_widget_size()
        self._update_rubber_band_from_pdf()

    def clear_content(self) -> None:
        self.pixmap = None
        self.page_rect = None
        self._pdf_selection = None
        self._selection_widget_rect = None
        self._rubber_band.hide()
        self.update()

    def set_page(self, page: fitz.Page, scale: float, keep_selection: bool = False) -> None:
        self.page_rect = page.rect
        self.scale_factor = scale
        self.pixmap = self._render_page_pixmap(page, scale)
        self._update_widget_size()
        if not keep_selection:
            self._pdf_selection = None
        self._update_rubber_band_from_pdf()
        self.update()

    def _update_widget_size(self) -> None:
        if not self.pixmap:
            return
        target_width = max(self.pixmap.width(), self._viewport_size.width())
        target_height = max(self.pixmap.height(), self._viewport_size.height())
        self.setMinimumSize(target_width, target_height)
        self.resize(target_width, target_height)

    def _render_page_pixmap(self, page: fitz.Page, scale: float) -> QPixmap:
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=True)
        if pix.alpha:
            fmt = QImage.Format.Format_RGBA8888
        else:
            fmt = QImage.Format.Format_RGB888
        qimage = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        qimage = qimage.copy()  # detach from Pixmap buffer
        return QPixmap.fromImage(qimage)

    def image_offsets(self) -> tuple[float, float]:
        if not self.pixmap:
            return 0.0, 0.0
        offset_x = max((self.width() - self.pixmap.width()) / 2, 0)
        offset_y = max((self.height() - self.pixmap.height()) / 2, 0)
        return offset_x, offset_y

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap:
            self._dragging = True
            self._drag_start = event.position().toPoint()
            self._rubber_band.setGeometry(QRect(self._drag_start, QSize()))
            self._rubber_band.show()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self.pixmap:
            rect = QRect(self._drag_start, event.position().toPoint()).normalized()
            self._rubber_band.setGeometry(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging and self.pixmap:
            self._dragging = False
            rect = QRectF(QRect(self._drag_start, event.position().toPoint()).normalized())
            self._selection_widget_rect = rect
            self._pdf_selection = self._widget_rect_to_pdf(rect)
            self._update_rubber_band_from_pdf()
            self.selection_changed.emit(self._pdf_selection)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.pixmap:
            return
        painter = QPainter(self)
        offset_x, offset_y = self.image_offsets()
        painter.drawPixmap(int(offset_x), int(offset_y), self.pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_rubber_band_from_pdf()

    def clear_selection(self) -> None:
        self._pdf_selection = None
        self._selection_widget_rect = None
        self._rubber_band.hide()
        self.selection_changed.emit(None)

    def current_pdf_rect(self) -> fitz.Rect | None:
        return self._pdf_selection

    def _update_rubber_band_from_pdf(self) -> None:
        if not (self.pixmap and self._pdf_selection):
            self._rubber_band.hide()
            return
        rect = self._pdf_rect_to_widget(self._pdf_selection)
        if rect.width() <= 0 or rect.height() <= 0:
            self._rubber_band.hide()
            return
        self._selection_widget_rect = rect
        self._rubber_band.setGeometry(rect.toRect())
        self._rubber_band.show()

    def _widget_rect_to_pdf(self, rect: QRectF) -> fitz.Rect | None:
        if not self.page_rect:
            return None
        offset_x, offset_y = self.image_offsets()
        x0 = (rect.left() - offset_x) / self.scale_factor
        y0 = (rect.top() - offset_y) / self.scale_factor
        x1 = x0 + rect.width() / self.scale_factor
        y1 = y0 + rect.height() / self.scale_factor

        # Normalize and clamp to page bounds
        norm = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        page_rect = self.page_rect
        clamped = fitz.Rect(
            max(page_rect.x0, norm.x0),
            max(page_rect.y0, norm.y0),
            min(page_rect.x1, norm.x1),
            min(page_rect.y1, norm.y1),
        )
        if clamped.width == 0 or clamped.height == 0:
            return None
        return clamped

    def _pdf_rect_to_widget(self, rect: fitz.Rect) -> QRectF:
        offset_x, offset_y = self.image_offsets()
        x0 = rect.x0 * self.scale_factor + offset_x
        y0 = rect.y0 * self.scale_factor + offset_y
        x1 = rect.x1 * self.scale_factor + offset_x
        y1 = rect.y1 * self.scale_factor + offset_y
        return QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Rect Picker")
        self.doc: fitz.Document | None = None
        self.current_page_index = 0
        self.scale_factor = 1.0

        self.viewer = PdfViewerWidget()
        self.scroll_area = ScrollAreaWithSignal()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.viewer)
        self.scroll_area.viewport_resized.connect(self.viewer.set_viewport_size)

        self.rect_label = QLabel("Rect: -")
        self.size_label = QLabel("Size: -")
        self.page_label = QLabel("Page: -")
        self.page_info_label = QLabel("Page: -")
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)

        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self) -> None:
        open_btn = QPushButton("Open PDF")
        prev_btn = QPushButton("Previous Page")
        next_btn = QPushButton("Next Page")
        zoom_in_btn = QPushButton("Zoom In")
        zoom_out_btn = QPushButton("Zoom Out")
        reset_zoom_btn = QPushButton("Reset Zoom")
        copy_btn = QPushButton("Copy Rect")

        open_btn.clicked.connect(self.open_pdf)
        prev_btn.clicked.connect(self.prev_page)
        next_btn.clicked.connect(self.next_page)
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_out_btn.clicked.connect(self.zoom_out)
        reset_zoom_btn.clicked.connect(self.reset_zoom)
        copy_btn.clicked.connect(self.copy_rect)

        self.buttons = {
            "open": open_btn,
            "prev": prev_btn,
            "next": next_btn,
            "zoom_in": zoom_in_btn,
            "zoom_out": zoom_out_btn,
            "reset_zoom": reset_zoom_btn,
            "copy": copy_btn,
        }

        controls = QHBoxLayout()
        controls.addWidget(open_btn)
        controls.addWidget(prev_btn)
        controls.addWidget(next_btn)
        controls.addWidget(zoom_in_btn)
        controls.addWidget(zoom_out_btn)
        controls.addWidget(reset_zoom_btn)
        controls.addWidget(copy_btn)
        controls.addStretch()
        controls.addWidget(self.page_label)

        info_layout = QVBoxLayout()
        info_layout.addWidget(self.rect_label)
        info_layout.addWidget(self.size_label)
        info_layout.addWidget(self.page_info_label)
        info_layout.addWidget(QLabel("JSON:"))
        info_layout.addWidget(self.json_view)

        info_box = QGroupBox("Info")
        info_box.setLayout(info_layout)

        main_layout = QVBoxLayout()
        main_layout.addLayout(controls)

        content_layout = QHBoxLayout()
        content_layout.addWidget(self.scroll_area, stretch=3)
        content_layout.addWidget(info_box, stretch=1)
        main_layout.addLayout(content_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.viewer.selection_changed.connect(self.update_selection_info)
        self._update_controls()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence.StandardKey.ZoomIn, self, activated=self.zoom_in)
        QShortcut(QKeySequence.StandardKey.ZoomOut, self, activated=self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.reset_zoom)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self.copy_rect)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.clear_selection)

    def open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", str(Path.home()), "PDF Files (*.pdf)")
        if not path:
            return
        try:
            doc = fitz.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to open PDF:\n{exc}")
            return
        self.doc = doc
        self.current_page_index = 0
        self.scale_factor = 1.0
        self.load_page(keep_selection=False)
        self.setWindowTitle(f"PDF Rect Picker - {Path(path).name}")
        self._update_controls()

    def load_page(self, keep_selection: bool) -> None:
        if not self.doc:
            return
        page = self.doc.load_page(self.current_page_index)
        self.viewer.set_page(page, self.scale_factor, keep_selection=keep_selection)
        self.page_label.setText(f"Page: {self.current_page_index + 1} / {self.doc.page_count}")
        self.page_info_label.setText(f"Page: {self.current_page_index + 1} / {self.doc.page_count}")
        if not keep_selection:
            self.clear_selection()

    def next_page(self) -> None:
        if self.doc and self.current_page_index < self.doc.page_count - 1:
            self.current_page_index += 1
            self.load_page(keep_selection=False)
            self._update_controls()

    def prev_page(self) -> None:
        if self.doc and self.current_page_index > 0:
            self.current_page_index -= 1
            self.load_page(keep_selection=False)
            self._update_controls()

    def zoom_in(self) -> None:
        if not self.doc:
            return
        self.scale_factor = min(self.scale_factor * 1.25, 6.0)
        self.load_page(keep_selection=True)

    def zoom_out(self) -> None:
        if not self.doc:
            return
        self.scale_factor = max(self.scale_factor / 1.25, 0.2)
        self.load_page(keep_selection=True)

    def reset_zoom(self) -> None:
        if not self.doc:
            return
        self.scale_factor = 1.0
        self.load_page(keep_selection=True)

    def clear_selection(self) -> None:
        self.viewer.clear_selection()

    def copy_rect(self) -> None:
        rect = self.viewer.current_pdf_rect()
        if not rect:
            return
        rect_text = f"fitz.Rect({rect.x0:.2f}, {rect.y0:.2f}, {rect.x1:.2f}, {rect.y1:.2f})"
        QGuiApplication.clipboard().setText(rect_text)

    def update_selection_info(self, rect: fitz.Rect | None) -> None:
        if rect:
            rect_text = f"Rect: ({rect.x0:.2f}, {rect.y0:.2f}, {rect.x1:.2f}, {rect.y1:.2f})"
            size_text = f"Size: {rect.width:.2f} x {rect.height:.2f}"
            json_text = json.dumps({"page": self.current_page_index + 1, "rect": [rect.x0, rect.y0, rect.x1, rect.y1]}, indent=2)
        else:
            rect_text = "Rect: -"
            size_text = "Size: -"
            json_text = ""
        self.rect_label.setText(rect_text)
        self.size_label.setText(size_text)
        self.json_view.setPlainText(json_text)
        self._update_controls()

    def _update_controls(self) -> None:
        has_doc = self.doc is not None
        has_rect = self.viewer.current_pdf_rect() is not None
        self.buttons["prev"].setEnabled(has_doc and self.current_page_index > 0)
        self.buttons["next"].setEnabled(has_doc and self.doc and self.current_page_index < self.doc.page_count - 1)
        self.buttons["zoom_in"].setEnabled(has_doc)
        self.buttons["zoom_out"].setEnabled(has_doc)
        self.buttons["reset_zoom"].setEnabled(has_doc)
        self.buttons["copy"].setEnabled(has_rect)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
