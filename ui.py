import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QLabel,
    QFileDialog,
    QVBoxLayout,
    QLineEdit,
    QMessageBox,
)

from transcriber import generate_srt

QApplication.processEvents()


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setAcceptDrops(True)

        self.audio_path = None

        self.setWindowTitle("Shorts Caption Generator")
        self.resize(350, 180)

        self.label = QLabel("No file selected")
        self.default_style = self.styleSheet()

        self.select_button = QPushButton("Select or Drag & Drop MP3")
        self.generate_button = QPushButton("Generate")

        self.generate_button.setEnabled(False)

        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText("Leave empty = same name as audio")

        self.open_button = QPushButton("Open Output Folder")

        self.open_button.setEnabled(False)

        layout = QVBoxLayout()

        layout.addWidget(self.select_button)
        layout.addWidget(self.label)
        layout.addWidget(self.generate_button)
        layout.addWidget(QLabel("Output filename"))
        layout.addWidget(self.output_name)
        layout.addWidget(self.open_button)
        self.setLayout(layout)

        self.select_button.clicked.connect(self.select_file)
        self.generate_button.clicked.connect(self.generate)

        self.open_button.clicked.connect(self.open_folder)

    def select_file(self):

        file, _ = QFileDialog.getOpenFileName(
            self,
            "Select MP3",
            "",
            "Audio (*.mp3)"
        )

        if file:

            self.audio_path = file

            self.label.setText(file.split("/")[-1])

            self.generate_button.setEnabled(True)

    def generate(self):
        self.generate_button.setEnabled(False)
        self.select_button.setEnabled(False)

        self.label.setText("Generating...")

        name = self.output_name.text().strip()

        if name == "":
            name = None

        self.generate_button.setText("Generating...")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()

        alignment_warnings = []
        try:
            output = generate_srt(self.audio_path, name, on_warning=alignment_warnings.append)

        except Exception as error:
            self.label.setText("Generation failed")
            QMessageBox.critical(self, "Generation failed", str(error))
            return

        finally:
            QApplication.restoreOverrideCursor()

            self.generate_button.setEnabled(True)
            self.select_button.setEnabled(True)
            self.generate_button.setText("Generate")

        self.open_button.setEnabled(True)

        if alignment_warnings:
            QMessageBox.warning(self, "Timing notice", "\n".join(alignment_warnings))

        QMessageBox.information(
            self,
            "Done",
            f"Captions saved to:\n\n{output}"
        )

        self.generate_button.setEnabled(True)
        self.select_button.setEnabled(True)

        self.open_button.setEnabled(True)

    def dragEnterEvent(self, event: QDragEnterEvent):

        if event.mimeData().hasUrls():

            file = event.mimeData().urls()[0].toLocalFile()

            if file.lower().endswith(".mp3"):
                self.setStyleSheet("""
                    QWidget{
                        background:#d8ecff;
                        border:3px dashed #3399ff;
                    }
                """)

                self.label.setText("🎵 Drop MP3 here")

                event.acceptProposedAction()

    def dragLeaveEvent(self, event):

        self.setStyleSheet(self.default_style)

        if self.audio_path:
            self.label.setText(os.path.basename(self.audio_path))
        else:
            self.label.setText("No file selected")

    def dropEvent(self, event: QDropEvent):

        self.setStyleSheet(self.default_style)

        file = event.mimeData().urls()[0].toLocalFile()

        if file.lower().endswith(".mp3"):

            self.audio_path = file
            self.label.setText("🎵 " + os.path.basename(file))
            self.label.setText(os.path.basename(file))

            self.generate_button.setEnabled(True)

    def open_folder(self):

        if self.audio_path:

            os.startfile(os.path.dirname(self.audio_path))
