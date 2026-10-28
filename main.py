import sys
from multiprocessing import freeze_support


def main():
	from PySide6.QtWidgets import QApplication
	from ui import MainWindow

	app = QApplication(sys.argv)
	window = MainWindow()
	window.show()
	return app.exec()


if __name__ == "__main__":
	freeze_support()
	sys.exit(main())
