from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
	QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
	QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
	QTextEdit, QVBoxLayout, QWidget,
)

from capcut_generator import generate_project, inspect_reference


class GenerationWorker(QThread):
	progress = Signal(str)
	succeeded = Signal(str, list)
	failed = Signal(str)

	def __init__(self, options, parent=None):
		super().__init__(parent)
		self.options = options

	def run(self):
		try:
			path, warnings = generate_project(**self.options, progress=self.progress.emit)
			self.succeeded.emit(str(path), warnings)
		except Exception as error:
			self.failed.emit(str(error))


class CapCutGeneratorDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle('CapCut Draft Generator — Initial Version')
		self.resize(900, 720)
		self.tracks = []
		self.slots = []
		self.worker = None
		self.result_path = None
		layout = QVBoxLayout(self)
		notice = QLabel('Automatic rough cut: no recorded jokes and no captions required.\n'
			'Chooses local memes and sounds by filenames/folders, not visual AI. Keeps template pacing, freezes and existing effects.\n'
			'Replaces old speech with silent JOKE slots for your future lines. Review choices in CapCut; captions come later.')
		notice.setWordWrap(True)
		layout.addWidget(notice)
		self.inputs = QWidget()
		form = QFormLayout(self.inputs)
		self.reference = QLineEdit()
		self.reference.setReadOnly(True)
		form.addRow('Reference project folder', self.file_row(self.reference, self.choose_reference, 'Browse...'))
		self.drawing = QLineEdit()
		self.drawing.setReadOnly(True)
		form.addRow('New drawing video', self.file_row(self.drawing, self.choose_drawing, 'Browse...'))
		self.memes = QLineEdit()
		self.sounds = QLineEdit()
		form.addRow('Memes folder', self.file_row(self.memes, lambda: self.choose_folder(self.memes), 'Browse...'))
		form.addRow('Voices / sound-effects folder', self.file_row(self.sounds, lambda: self.choose_folder(self.sounds), 'Browse...'))
		self.topic = QLineEdit()
		self.topic.setPlaceholderText('Optional: pig, phone, surprise — filename matching hints')
		form.addRow('Topic / keywords', self.topic)
		self.name = QLineEdit('generated-short')
		form.addRow('New project name', self.name)
		self.video_track = QComboBox()
		self.audio_track = QComboBox()
		form.addRow('Drawing track', self.video_track)
		form.addRow('Reference speech track → joke slots', self.audio_track)
		self.audio_track.currentIndexChanged.connect(self.refresh_slots)
		self.table = QTableWidget(0, 2)
		self.table.setHorizontalHeaderLabels(['Joke start / duration', 'Reference clip (removed)'])
		self.table.setColumnWidth(0, 120)
		self.table.setColumnWidth(1, 250)
		self.table.setMinimumHeight(230)
		self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
		form.addRow(self.table)
		self.closed = QCheckBox('CapCut is closed. I understand this keeps the reference timing and inherited effects.')
		form.addRow(self.closed)
		layout.addWidget(self.inputs)
		self.generate = QPushButton('Generate editable CapCut project')
		self.generate.clicked.connect(self.start_generation)
		layout.addWidget(self.generate)
		self.log = QTextEdit()
		self.log.setReadOnly(True)
		layout.addWidget(self.log)
		self.open_folder = QPushButton('Open generated project folder')
		self.open_folder.setEnabled(False)
		self.open_folder.clicked.connect(self.show_folder)
		layout.addWidget(self.open_folder)

	def file_row(self, field, action, label):
		widget = QWidget()
		row = QHBoxLayout(widget)
		row.setContentsMargins(0, 0, 0, 0)
		row.addWidget(field)
		button = QPushButton(label)
		button.clicked.connect(action)
		row.addWidget(button)
		return widget

	def choose_reference(self):
		folder = QFileDialog.getExistingDirectory(self, 'Select folder containing draft_content.json')
		if not folder:
			return
		try:
			_, tracks = inspect_reference(folder)
			if any(not any(t['type'] == kind for t in tracks) for kind in ('video', 'audio')):
				raise ValueError('Reference needs drawing and speech tracks to define editable joke slots.')
		except Exception as error:
			QMessageBox.warning(self, 'Unsupported reference', str(error))
			return
		self.reference.setText(folder)
		self.tracks = tracks
		self.audio_track.blockSignals(True)
		for combo, kind in ((self.video_track, 'video'), (self.audio_track, 'audio')):
			combo.clear()
			for track in tracks:
				if track['type'] == kind:
					label = f"Track {track['index'] + 1}: {len(track['slots'])} clips — {track['slots'][0]['label']}"
					combo.addItem(label, track['index'])
		self.audio_track.blockSignals(False)
		self.refresh_slots()
		self.name.setText(Path(folder).name + '-generated')

	def choose_drawing(self):
		path, _ = QFileDialog.getOpenFileName(self, 'New drawing video', '', 'Video (*.mp4 *.mov *.mkv *.webm)')
		if path:
			self.drawing.setText(path)

	def choose_folder(self, field):
		path = QFileDialog.getExistingDirectory(self, 'Select asset library folder')
		if path:
			field.setText(path)

	def refresh_slots(self):
		track = next((t for t in self.tracks if t['index'] == self.audio_track.currentData()), None)
		self.slots = track['slots'] if track else []
		self.table.setRowCount(len(self.slots))
		for row, slot in enumerate(self.slots):
			self.table.setItem(row, 0, QTableWidgetItem(f"{slot['start'] / 1e6:.2f}s / {slot['duration'] / 1e6:.2f}s"))
			self.table.setItem(row, 1, QTableWidgetItem(slot['label']))

	def start_generation(self):
		if not self.closed.isChecked():
			QMessageBox.warning(self, 'Close CapCut', 'Close CapCut first and tick the confirmation box.')
			return
		if not self.reference.text() or not self.drawing.text() or not self.slots:
			QMessageBox.warning(self, 'Missing input', 'Choose a reference, drawing video and tracks first.')
			return
		if not self.memes.text() or not self.sounds.text():
			QMessageBox.warning(self, 'Missing libraries', 'Choose memes and sound-effects folders.')
			return
		options = dict(reference=self.reference.text(), drawing=self.drawing.text(), replacements={},
			video_track=self.video_track.currentData(), audio_track=self.audio_track.currentData(),
			text_track=None, project_name=self.name.text(), automatic=True,
			meme_folder=self.memes.text(), sound_folder=self.sounds.text(), topic=self.topic.text())
		self.inputs.setEnabled(False)
		self.generate.setEnabled(False)
		self.open_folder.setEnabled(False)
		self.log.clear()
		self.worker = GenerationWorker(options, self)
		self.worker.progress.connect(self.log.append)
		self.worker.succeeded.connect(self.on_success)
		self.worker.failed.connect(self.on_failure)
		self.worker.finished.connect(self.on_finished)
		self.worker.start()

	def on_success(self, path, warnings):
		self.result_path = path
		self.log.append('Created: ' + path)
		for warning in warnings:
			self.log.append('Review: ' + warning)
		self.open_folder.setEnabled(True)
		QMessageBox.information(self, 'Draft created', 'Reopen CapCut and look for ' + Path(path).name + '.\nReview the notes below before using the result.')

	def on_failure(self, message):
		self.log.append('Failed: ' + message)
		QMessageBox.critical(self, 'Generation failed', message)

	def on_finished(self):
		self.inputs.setEnabled(True)
		self.generate.setEnabled(True)
		self.worker.deleteLater()
		self.worker = None

	def show_folder(self):
		import os
		if self.result_path:
			os.startfile(self.result_path)

	def reject(self):
		if self.worker is not None:
			QMessageBox.information(self, 'Generation in progress', 'Wait for generation to finish before closing.')
			return
		super().reject()

	def closeEvent(self, event):
		if self.worker is not None:
			event.ignore()
		else:
			super().closeEvent(event)
