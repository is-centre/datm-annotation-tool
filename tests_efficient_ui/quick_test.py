from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QImage, QPixmap, QPainterPath
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QFileDialog

TEST_IMAGE_PATH = "C:\\Users\\Alex\\Desktop\\SomeTests\\20190414_083725_LD5-050.marked.jpg"

class Window(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        top, left, width, height = 20, 20, 800, 600
        self.setWindowTitle("MyPainter")
        self.setGeometry(top, left, width, height)

        #self.image = QtGui.QImage(self.size(), QtGui.QImage.Format_ARGB32)
        #self.image.fill(QtCore.Qt.white)
        self.image = QImage(TEST_IMAGE_PATH)
        self.imageDraw = QtGui.QImage(self.size(), QtGui.QImage.Format_ARGB32)
        self.imageDraw.fill(QtCore.Qt.transparent)

        self.drawing = False
        self.brushSize = 10
        self._clear_size = 20
        self.brushColor = QtGui.QColor(255, 0, 0)
        self.lastPoint = QtCore.QPoint()

        self.change = False
        mainMenu = self.menuBar()

        loadImage = mainMenu.addMenu("File")
        loadImageAction = QtWidgets.QAction("Load", self)
        loadImage.addAction(loadImageAction)
        loadImageAction.triggered.connect(self.openImage)

        changeColour = mainMenu.addMenu("Mode")
        changeColourAction = QtWidgets.QAction("Erase", self)
        changeColour.addAction(changeColourAction)
        changeColourAction.triggered.connect(self.changeColour)

        # Brush cursor
        pixmap = QtGui.QPixmap(QtCore.QSize(1, 1) * self.brushSize)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QPen(QtCore.Qt.black, 2))
        painter.drawEllipse(pixmap.rect())
        painter.end()
        cursor = QtGui.QCursor(pixmap)
        QtWidgets.QApplication.setOverrideCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drawing = True
            self.lastPoint = event.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() and QtCore.Qt.LeftButton and self.drawing:
            painter = QtGui.QPainter(self.imageDraw)
            painter.setPen(QtGui.QPen(self.brushColor, self.brushSize, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
            if self.change:
                r = QtCore.QRect(QtCore.QPoint(), self._clear_size*QtCore.QSize())
                r.moveCenter(event.pos())
                painter.save()
                painter.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
                painter.eraseRect(r)
                painter.restore()
            else:
                painter.drawLine(self.lastPoint, event.pos())
            painter.end()
            self.lastPoint = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button == QtCore.Qt.LeftButton:
            self.drawing = False

    def resizeEvent(self, event):
        print("Resized")

    def paintEvent(self, event):

        # Some debugging to see how it works
        (a,b,c,d) = self.image.rect().getRect()
        newRect = QtCore.QRect(a+100,b+100,c-100,d-100)

        canvasPainter = QtGui.QPainter(self)
        #canvasPainter.drawImage(self.rect(), self.image, self.image.rect()) # original
        canvasPainter.drawImage(self.rect(), self.image, newRect)
        canvasPainter.setOpacity(0.5)
        canvasPainter.drawImage(self.rect(), self.imageDraw, self.imageDraw.rect())

    def changeColour(self):
        self.change = not self.change
        if self.change:
            pixmap = QtGui.QPixmap(QtCore.QSize(1, 1)*self._clear_size)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setPen(QtGui.QPen(QtCore.Qt.black, 2))
            painter.drawRect(pixmap.rect())
            painter.end()
            cursor = QtGui.QCursor(pixmap)
            QtWidgets.QApplication.setOverrideCursor(cursor)
        else:
            # TODO: Commented below is default behavior. Should set this on MOUSE CANVAS LEAVE actually.
            #QtWidgets.QApplication.restoreOverrideCursor()
            pixmap = QtGui.QPixmap(QtCore.QSize(1, 1) * self.brushSize)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setPen(QtGui.QPen(QtCore.Qt.black, 2))
            painter.drawEllipse(pixmap.rect())
            painter.end()
            cursor = QtGui.QCursor(pixmap)
            QtWidgets.QApplication.setOverrideCursor(cursor)

    def openImage(self):
        fileName, dummy = QFileDialog.getOpenFileName(self, "Open image file.")
        self.image = QImage(fileName)

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = Window()
    window.show()
    sys.exit(app.exec())