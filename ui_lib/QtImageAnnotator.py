import os.path
import cv2
import numpy as np
from qimage2ndarray import alpha_view, array2qimage
from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QT_VERSION_STR, QPoint
from PyQt5.QtGui import QImage, QPixmap, QPainterPath, QPainter, QColor, QPen
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QFileDialog, QApplication

__author__ = "Aleksei Tepljakov <alex@starspirals.net>"
__original_author__ = "Marcel Goldschen-Ohm <marcel.goldschen@gmail.com>"
__original_title__ = "QtImageViewer"
__version__ = '1.0.0'

__debug_out__ = "C:\\Users\\Alex\\Desktop\\"

# Reusable component for painting over an image for, e.g., masking purposes
class QtImageAnnotator(QGraphicsView):

    # Mouse button signals emit image scene (x, y) coordinates.
    # !!! For image (row, column) matrix indexing, row = y and column = x.
    leftMouseButtonPressed = pyqtSignal(float, float)
    middleMouseButtonPressed = pyqtSignal(float, float)
    rightMouseButtonPressed = pyqtSignal(float, float)
    leftMouseButtonReleased = pyqtSignal(float, float)
    middleMouseButtonReleased = pyqtSignal(float, float)
    rightMouseButtonReleased = pyqtSignal(float, float)
    leftMouseButtonDoubleClicked = pyqtSignal(float, float)
    middleMouseButtonDoubleClicked = pyqtSignal(float, float)
    rightMouseButtonDoubleClicked = pyqtSignal(float, float)

    def __init__(self):
        QGraphicsView.__init__(self)

        # Image is displayed as a QPixmap in a QGraphicsScene attached to this QGraphicsView.
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # Store a local handle to the scene's current image pixmap.
        self._pixmapHandle = None  # This holds the image
        self._overlayHandle = None  # This is the overlay over which we are painting
        self._cursorHandle = None  # This is the cursor that appears to assist with brush size

        # Needed for proper drawing
        self.lastPoint = QPoint()
        self.lastCursorLocation = QPoint()

        # Pixmap that contains the mask and the corresponding painter
        self.mask_pixmap = None

        # Parameters of the brush and paint
        self.brush_diameter = 50
        self.brush_fill_color = QColor(255,0,70,99)

        # Painting and erasing modes
        self.MODE_PAINT = QPainter.RasterOp_SourceOrDestination
        self.MODE_ERASE = QPainter.CompositionMode_Clear
        self.current_painting_mode = self.MODE_PAINT

        # Make mouse events accessible
        self.setMouseTracking(True)

        # Image aspect ratio mode.
        #   Qt.IgnoreAspectRatio: Scale image to fit viewport.
        #   Qt.KeepAspectRatio: Scale image to fit inside viewport, preserving aspect ratio.
        #   Qt.KeepAspectRatioByExpanding: Scale image to fill the viewport, preserving aspect ratio.
        self.aspectRatioMode = Qt.KeepAspectRatio

        # Scroll bar behaviour.
        #   Qt.ScrollBarAlwaysOff: Never shows a scroll bar.
        #   Qt.ScrollBarAlwaysOn: Always shows a scroll bar.
        #   Qt.ScrollBarAsNeeded: Shows a scroll bar only when zoomed.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Stack of QRectF zoom boxes in scene coordinates.
        self.zoomStack = []

        # Flags for enabling/disabling mouse interaction.
        self.canZoom = True
        self.canPan = True

    def hasImage(self):
        """ Returns whether or not the scene contains an image pixmap.
        """
        return self._pixmapHandle is not None

    # def paintEvent(self, event):
    #     painter = QPainter(self)
    #
    #     if self._pixmapHandle is not None:
    #         painter.drawPixmap(self.rect(), self._pixmapHandle)
    #     if self._overlayHandle is not None:
    #         print("This isn't implemented yet")
    #     if self._cursorHandle is not None:
    #         painter.drawEllipse(self.rect(), self._cursorHandle)

    def clearImage(self):
        """ Removes the current image pixmap from the scene if it exists.
        """
        if self.hasImage():
            self.scene.removeItem(self._pixmapHandle)
            self._pixmapHandle = None

    def pixmap(self):
        """ Returns the scene's current image pixmap as a QPixmap, or else None if no image exists.
        :rtype: QPixmap | None
        """
        if self.hasImage():
            return self._pixmapHandle.pixmap()
        return None

    def image(self):
        """ Returns the scene's current image pixmap as a QImage, or else None if no image exists.
        :rtype: QImage | None
        """
        if self.hasImage():
            return self._pixmapHandle.pixmap().toImage()
        return None

    def setImage(self, image):
        """ Set the scene's current image pixmap to the input QImage or QPixmap.
        Raises a RuntimeError if the input image has type other than QImage or QPixmap.
        :type image: QImage | QPixmap
        """
        if type(image) is QPixmap:
            pixmap = image
        elif type(image) is QImage:
            pixmap = QPixmap.fromImage(image)
        else:
            raise RuntimeError("ImageViewer.setImage: Argument must be a QImage or QPixmap.")
        if self.hasImage():
            self._pixmapHandle.setPixmap(pixmap)
        else:
            self._pixmapHandle = self.scene.addPixmap(pixmap)

        self.setSceneRect(QRectF(pixmap.rect()))  # Set scene size to image size.

        # Add the mask layer
        self.mask_pixmap = QPixmap(pixmap.rect().width(), pixmap.rect().height())
        self.mask_pixmap.fill(QColor(0,0,0,0))
        self._overlayHandle = self.scene.addPixmap(self.mask_pixmap)

        # Add brush cursor to top layer
        self._cursorHandle = self.scene.addEllipse(0,0,self.brush_diameter,self.brush_diameter)

        self.updateViewer()

    def loadImageFromFile(self, fileName=""):
        """ Load an image from file.
        Without any arguments, loadImageFromFile() will popup a file dialog to choose the image file.
        With a fileName argument, loadImageFromFile(fileName) will attempt to load the specified image file directly.
        """
        if len(fileName) == 0:
            if QT_VERSION_STR[0] == '4':
                fileName = QFileDialog.getOpenFileName(self, "Open image file.")
            elif QT_VERSION_STR[0] == '5':
                fileName, dummy = QFileDialog.getOpenFileName(self, "Open image file.")
        if len(fileName) and os.path.isfile(fileName):
            image = QImage(fileName)
            self.setImage(image)

    def updateViewer(self):
        """ Show current zoom (if showing entire image, apply current aspect ratio mode).
        """
        if not self.hasImage():
            return
        if len(self.zoomStack) and self.sceneRect().contains(self.zoomStack[-1]):
            self.fitInView(self.zoomStack[-1], self.aspectRatioMode)   # Show zoomed rect
        else:
            self.zoomStack = []  # Clear the zoom stack (in case we got here because of an invalid zoom).
            self.fitInView(self.sceneRect(), self.aspectRatioMode)  # Show entire image (use current aspect ratio mode).

    def resizeEvent(self, event):
        """ Maintain current zoom on resize.
        """
        self.updateViewer()

    def update_cursor_location(self, event):
        # There's a problem with this cursor that it's too big.
        # self.viewport().setCursor(Qt.CrossCursor)

        scenePos = self.mapToScene(event.pos())
        x, y = scenePos.x(), scenePos.y()

        if self._cursorHandle is not None:
            self._cursorHandle.setPos(x - self.brush_diameter/2, y - self.brush_diameter/2)

    def redraw_cursor(self):
        if self._cursorHandle is not None:
            self._cursorHandle.update()

    def wheelEvent(self, event):

        self.redraw_cursor()
        QGraphicsView.wheelEvent(self, event)

    def mouseMoveEvent(self, event):

        self.update_cursor_location(event)

        # Support for panning
        if event.buttons() == Qt.MiddleButton:
            offset = self.__prevMousePos - event.pos()
            self.__prevMousePos = event.pos()
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + offset.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + offset.x())

        # Filling in the markers
        if event.buttons() == Qt.LeftButton:
            self.drawMarkerLine(event)

        # Store cursor location separately; needed for certain operations (like fill)
        self.lastCursorLocation = self.mapToScene(event.pos())

        QGraphicsView.mouseMoveEvent(self, event)

    # Draws a single ellipse
    def fillMarker(self, event):
        scenePos = self.mapToScene(event.pos())
        painter = QPainter(self.mask_pixmap)
        painter.setCompositionMode(self.current_painting_mode)
        painter.setPen(QColor(0,0,0,0))
        painter.setBrush(self.brush_fill_color)
        painter.drawEllipse(scenePos.x() - self.brush_diameter/2,
                            scenePos.y() - self.brush_diameter/2, self.brush_diameter, self.brush_diameter)
        self._overlayHandle.setPixmap(self.mask_pixmap)
        self.lastPoint = scenePos

    # Draws a line
    def drawMarkerLine(self, event):
        scenePos = self.mapToScene(event.pos())
        painter = QPainter(self.mask_pixmap)
        painter.setCompositionMode(self.current_painting_mode)
        painter.setPen(QPen(self.brush_fill_color,
                            self.brush_diameter, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(self.lastPoint, scenePos)
        self._overlayHandle.setPixmap(self.mask_pixmap)
        self.lastPoint = scenePos

    # Convert pixmap to numpy array
    @staticmethod
    def pixmap2np(pixmap):

        # Get shape info and convert to image
        width, height, depth = pixmap.rect().width(), pixmap.rect().height(), int(pixmap.depth()/8)
        print(depth)
        img = pixmap.toImage()

        # Convert to OpenCV format for processing and return the result
        s = img.bits().asstring(width * height * depth)
        arr = np.fromstring(s, dtype=np.uint8).reshape((height, width, depth))
        return arr

    @staticmethod
    def np2pixmap(arr):

        return False

    # Fills an area using the last stored cursor location
    def fillArea(self):

        # We first convert the mask to a QImage and then to ndarray
        msk = alpha_view(self.mask_pixmap.toImage())

        # Apply simple tresholding and invert the image
        msk[np.where((msk>0))] = 255
        msk = 255-msk

        # Fill the contour
        seed_point = (int(self.lastCursorLocation.x()), int(self.lastCursorLocation.y()))
        msk1 = np.copy(msk)
        cv2.floodFill(msk1, cv2.copyMakeBorder(cv2.bitwise_not(msk), 1, 1, 1, 1, cv2.BORDER_CONSTANT, 0),
                      seed_point, 0, 0, 1)

        # Now we need to replace the pixmap
        h,w = msk1.shape
        new_img = np.zeros((h,w,4), np.uint8)
        new_img[np.where((msk1==0))] = list(self.brush_fill_color.getRgb())

        new_qimg = array2qimage(new_img)
        self.mask_pixmap = QPixmap.fromImage(new_qimg)
        self._overlayHandle.setPixmap(self.mask_pixmap)

    # We press F to fill a given area
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F:
            self.fillArea()

    def mousePressEvent(self, event):
        """ Start drawing, panning with mouse, or zooming in
        """

        scenePos = self.mapToScene(event.pos())
        if event.button() == Qt.LeftButton:

            # If SHIFT is held, draw a line
            if QApplication.keyboardModifiers() & Qt.ShiftModifier:
                self.drawMarkerLine(event)

            # If CONTROL is held, erase
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.current_painting_mode = self.MODE_ERASE
            else:
                self.current_painting_mode = self.MODE_PAINT

            # If the user just clicks, add a marker
            self.fillMarker(event)

            self.leftMouseButtonPressed.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.MiddleButton:
            if self.canPan:
                self.__prevMousePos = event.pos()
                self.viewport().setCursor(Qt.ClosedHandCursor)
            self._cursorHandle.hide()
            self.middleMouseButtonPressed.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.RightButton:
            if self.canZoom:
                self.setDragMode(QGraphicsView.RubberBandDrag)
            self._cursorHandle.hide()
            self.rightMouseButtonPressed.emit(scenePos.x(), scenePos.y())
        QGraphicsView.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        """ Stop mouse pan or zoom mode (apply zoom if valid).
        """
        QGraphicsView.mouseReleaseEvent(self, event)
        scenePos = self.mapToScene(event.pos())
        if event.button() == Qt.MiddleButton:
            self.viewport().setCursor(Qt.ArrowCursor)
            self._cursorHandle.show()
            self.middleMouseButtonReleased.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.RightButton:
            if self.canZoom:
                viewBBox = self.zoomStack[-1] if len(self.zoomStack) else self.sceneRect()
                selectionBBox = self.scene.selectionArea().boundingRect().intersected(viewBBox)
                self.scene.setSelectionArea(QPainterPath())  # Clear current selection area.
                if selectionBBox.isValid() and (selectionBBox != viewBBox):
                    self.zoomStack.append(selectionBBox)
                    self.updateViewer()
            self.setDragMode(QGraphicsView.NoDrag)
            self._cursorHandle.show()
            self.rightMouseButtonReleased.emit(scenePos.x(), scenePos.y())

    def mouseDoubleClickEvent(self, event):
        """ Show entire image.
        """
        scenePos = self.mapToScene(event.pos())
        if event.button() == Qt.MiddleButton:
            self.middleMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.RightButton:
            if self.canZoom:
                self.zoomStack = []  # Clear zoom stack.
                self.updateViewer()
            self.rightMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
        QGraphicsView.mouseDoubleClickEvent(self, event)

if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication

    def handleMiddleClick(x, y):
        row = int(y)
        column = int(x)

    # Create the application.
    app = QApplication(sys.argv)

    # Create image viewer and load an image file to display.
    viewer = QtImageAnnotator()
    viewer.loadImageFromFile()  # Pops up file dialog.

    # Show viewer and run application.
    viewer.show()
    sys.exit(app.exec_())
