import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QSlider, QPushButton
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QTimer, Qt
import cv2
from pypylon import pylon
import numpy as np

import os
os.environ["PYLON_CAMEMU"] = "1"

class CameraWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Connecting to the first available camera
        self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        self.gain_min = self.camera.GainRaw.GetMin()
        self.gain_max = self.camera.GainRaw.GetMax()

        # Set up a timer to call the update function regularly
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)  # Update every 30 ms

        # Initialize points for perspective transform
        self.points = []
        self.rect_width = 300
        self.rect_height = 200
        self.image = None
        self.transformed_image = None
        self.updating = True   

        self.initUI()
        self.update_frame()

    def initUI(self):
        self.setWindowTitle('Basler Camera Feed')
        self.setGeometry(100, 100, 1200, 600)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)

        self.transformed_label = QLabel(self)
        self.transformed_label.setAlignment(Qt.AlignCenter)

        self.captured_label = QLabel(self)
        self.captured_label.setAlignment(Qt.AlignCenter)

        self.capture_button = QPushButton('Capture')
        self.capture_button.clicked.connect(self.capture_image)

        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setMinimum(self.gain_min)
        self.gain_slider.setMaximum(self.gain_max)
        self.gain_slider.setValue(self.gain_min)
        self.gain_slider.valueChanged.connect(self.set_gain)
        
        self.toggle_button = QPushButton('Stop Update')
        self.toggle_button.clicked.connect(self.toggle_update)

        cap_layout = QVBoxLayout()
        cap_layout.addWidget(self.transformed_label)
        cap_layout.addWidget(self.captured_label)

        layout = QHBoxLayout()
        layout.addWidget(self.label)
        layout.addLayout(cap_layout)

        layout2 = QHBoxLayout()
        layout2.addWidget(QLabel("Gain"))
        layout2.addWidget(self.gain_slider)
        layout2.addWidget(self.toggle_button)
        layout2.addWidget(self.capture_button)

        vlayout = QVBoxLayout()
        vlayout.addLayout(layout)
        vlayout.addLayout(layout2)

        container = QWidget()
        container.setLayout(vlayout)

        self.setCentralWidget(container)

    def set_gain(self, value):
        self.camera.GainRaw.SetValue(value)
        print(self.camera.GainRaw.GetValue())

    def capture_image(self):
        if self.transformed_image is not None:
            # Resize the captured image to fit the label, keeping the aspect ratio
            img_resized = self.resize_image_keep_aspect_ratio(self.transformed_image, self.captured_label.width(), self.captured_label.height())

            # Convert the image to Qt format
            height, width, channel = img_resized.shape
            bytesPerLine = 3 * width
            qImg = QImage(img_resized.data, width, height, bytesPerLine, QImage.Format_BGR888)

            # Display the captured image in the label
            self.captured_label.setPixmap(QPixmap.fromImage(qImg))

    def mousePressEvent(self, event):
        if len(self.points) >= 4: self.points = []
            
        if self.image is None:
            return

        x = event.pos().x() - self.label.geometry().x()
        y = event.pos().y() - self.label.geometry().y()

        # Get the size and position of the resized image
        label_width = self.label.width()
        label_height = self.label.height()
        img_height, img_width = self.image.shape[:2]
        aspect_ratio = img_width / img_height

        if img_width / label_width > img_height / label_height:
            new_width = label_width
            new_height = int(label_width / aspect_ratio)
        else:
            new_height = label_height
            new_width = int(label_height * aspect_ratio)

        offset_x = (label_width - new_width) // 2
        offset_y = (label_height - new_height) // 2

        if offset_x <= x <= offset_x + new_width and offset_y <= y <= offset_y + new_height:
            img_x = int((x - offset_x) * img_width / new_width)
            img_y = int((y - offset_y) * img_height / new_height)

            if len(self.points) < 4:
                self.points.append((img_x, img_y))
                print(f"Point {len(self.points)}: ({img_x}, {img_y})")
            if len(self.points) == 4:
                print("Selected 4 points:", self.points)

    def toggle_update(self):
        if self.updating:
            self.timer.stop()
            self.toggle_button.setText('Start Update')
        else:
            self.timer.start(30)
            self.toggle_button.setText('Stop Update')
        self.updating = not self.updating

    def update_frame(self):
        if self.camera.IsGrabbing():
            grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            if grabResult.GrabSucceeded():
                image = self.converter.Convert(grabResult)
                img = image.GetArray()

                self.image = img

                # Draw the selected rectangle if there are points
                img_with_rect = img.copy()
                if len(self.points) > 0:
                    pts = np.array(self.points, np.int32)
                    cv2.polylines(img_with_rect, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

                # Resize the image to fit the window, keeping the aspect ratio
                img_resized = self.resize_image_keep_aspect_ratio(img_with_rect, self.label.width(), self.label.height())

                # Convert the image to Qt format
                height, width, channel = img_resized.shape
                bytesPerLine = 3 * width
                qImg = QImage(img_resized.data, width, height, bytesPerLine, QImage.Format_BGR888)

                # Display the image in the label
                self.label.setPixmap(QPixmap.fromImage(qImg))

                # If four points are selected, apply perspective transform
                if len(self.points) == 4:
                    pts1 = np.float32(self.points)
                    pts2 = np.float32([[0, 0], [self.rect_width, 0], [self.rect_width, self.rect_height], [0, self.rect_height]])

                    # Get the transformation matrix and apply perspective transform
                    M = cv2.getPerspectiveTransform(pts1, pts2)
                    self.transformed_image = cv2.warpPerspective(img, M, (self.rect_width, self.rect_height))

                    # Convert the transformed image to Qt format
                    qimg = QImage(self.transformed_image.data, self.rect_width, self.rect_height, self.rect_width * 3, QImage.Format_BGR888)
                    self.transformed_label.setPixmap(QPixmap.fromImage(qimg))

            grabResult.Release()

    def resize_image_keep_aspect_ratio(self, img, max_width, max_height):
        height, width = img.shape[:2]
        aspect_ratio = width / height

        if width > max_width or height > max_height:
            if width / max_width > height / max_height:
                new_width = max_width
                new_height = int(max_width / aspect_ratio)
            else:
                new_height = max_height
                new_width = int(max_height * aspect_ratio)
        else:
            new_width = width
            new_height = height

        resized_img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)
        return resized_img

    def closeEvent(self, event):
        self.camera.StopGrabbing()
        cv2.destroyAllWindows()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainWindow = CameraWindow()
    mainWindow.show()
    sys.exit(app.exec_())
