#!/usr/bin/env python3
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pathlib import Path

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Fingerprint Control Center')
        # Set window icon if exists
        icon_path = Path('/usr/share/pixmaps/fprint-control-center.png')
        if not icon_path.is_file():
            icon_path = Path(__file__).resolve().parent.parent / 'resources' / 'icon.png'
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        label = QLabel('Fingerprint Control Center UI')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(label)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(400, 300)
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
