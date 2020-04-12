import os.path
import cv2
import numpy as np
import collections
from qimage2ndarray import rgb_view, alpha_view, array2qimage
from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QT_VERSION_STR, QPoint
from PyQt5.QtGui import QImage, QPixmap, QPainterPath, QPainter, QColor, QPen
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QFileDialog, QApplication

__author__ = "Aleksei Tepljakov <alex@starspirals.net>"
__original_author__ = "Marcel Goldschen-Ohm <marcel.goldschen@gmail.com>"
__original_title__ = "QtImageViewer"
__version__ = '1.0.0'

__debug_out__ = "C:\\Users\\Aleksei\\Desktop\\"

MAX_CTRLZ_STATES = 10

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
    mouseWheelRotated = pyqtSignal(float)

    def __init__(self):
        QGraphicsView.__init__(self)

        # Image is displayed as a QPixmap in a QGraphicsScene attached to this QGraphicsView.
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # Store a local handle to the scene's current image pixmap.
        self._pixmapHandle = None  # This holds the image
        self._helperHandle = None # This holds the "helper" overlay which is not directly manipulated by the user
        self._overlayHandle = None  # This is the overlay over which we are painting
        self._cursorHandle = None  # This is the cursor that appears to assist with brush size
        self._deleteCrossHandles = None # For showing that we've activated delete mode

        self._lastCursorCoords = None # Latest coordinates of the cursor, need in some cursor overlay update operations

        self._overlay_stack = collections.deque(maxlen=MAX_CTRLZ_STATES)

        # Needed for proper drawing
        self.lastPoint = QPoint()
        self.lastCursorLocation = QPoint()

        # Pixmap that contains the mask and the corresponding painter
        self.mask_pixmap = None

        # Parameters of the brush and paint
        self.brush_diameter = 50
        self.MIN_BRUSH_DIAMETER = 1
        self.MAX_BRUSH_DIAMETER = 500

        self.brush_fill_color = QColor(255,0,0,99)

        # Painting and erasing modes
        self.MODE_PAINT = QPainter.RasterOp_SourceOrDestination
        self.MODE_ERASE = QPainter.CompositionMode_Clear
        self.current_painting_mode = self.MODE_PAINT
        self.global_erase_override = False

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


    def clearAndSetImageAndMask(self, image, mask, helper=None):
        # Clear the scene
        self.scene.clear()

        # Clear handles
        self._pixmapHandle = None
        self._helperHandle = None
        self._overlayHandle = None
        self._overlayHandle = None

        # Clear UNDO stack
        self._overlay_stack = collections.deque(maxlen=MAX_CTRLZ_STATES)

        # First we just set the image
        if type(image) is QPixmap:
            pixmap = image
        elif type(image) is QImage:
            pixmap = QPixmap.fromImage(image)
        else:
            raise RuntimeError("QtImageAnnotator.clearAndSetImageAndMask: Argument must be a QImage or QPixmap.")

        self._pixmapHandle = self.scene.addPixmap(pixmap)
        self.setSceneRect(QRectF(pixmap.rect()))

        # Now we add the helper, if present
        if helper is not None:
            if type(helper) is QPixmap:
                pixmap = helper
            elif type(image) is QImage:
                pixmap = QPixmap.fromImage(helper)
            else:
                raise RuntimeError("QtImageAnnotator.clearAndSetImageAndMask: Argument must be a QImage or QPixmap.")

            # Add the helper layer
            self._helperHandle = self.scene.addPixmap(pixmap)

        # Now we change the mask as well
        if type(mask) is QPixmap:
            pixmap = mask
        elif type(mask) is QImage:
            pixmap = QPixmap.fromImage(mask)
        else:
            raise RuntimeError("QtImageAnnotator.clearAndSetImageAndMask: Argument must be a QImage or QPixmap.")

        self.mask_pixmap = pixmap
        self._overlayHandle = self.scene.addPixmap(self.mask_pixmap)

        # Add brush cursor to top layer
        self._cursorHandle = self.scene.addEllipse(0, 0, self.brush_diameter, self.brush_diameter)

        # Add also X to the cursor for "delete" operation, and hide it by default only showing it when the
        # either the global drawing mode is set to ERASE or when CTRL is held while drawing
        self._deleteCrossHandles = (self.scene.addLine(0, 0, self.brush_diameter, self.brush_diameter),
                                    self.scene.addLine(0, self.brush_diameter, self.brush_diameter, 0))

        if self.current_painting_mode is not self.MODE_ERASE:
            self._deleteCrossHandles[0].hide()
            self._deleteCrossHandles[1].hide()

        self.updateViewer()

    # Clear everything
    def clearAll(self):

        if self._pixmapHandle is not None:
            self.scene.removeItem(self._pixmapHandle)

        if self._helperHandle is not None:
            self.scene.removeItem(self._helperHandle)

        if self._overlayHandle is not None:
            self.scene.removeItem(self._overlayHandle)

        self._pixmapHandle = None
        self._helperHandle = None
        self._overlayHandle = None

        self._overlay_stack = collections.deque(maxlen=MAX_CTRLZ_STATES)
        self.updateViewer()

    # Set image only
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

        # Add also X to the cursor for "delete" operation, and hide it by default only showing it when the
        # either the global drawing mode is set to ERASE or when CTRL is held while drawing
        self._deleteCrossHandles = (self.scene.addLine(0, 0, self.brush_diameter, self.brush_diameter),
                                    self.scene.addLine(0, self.brush_diameter, self.brush_diameter, 0))

        if self.current_painting_mode is not self.MODE_ERASE:
            self._deleteCrossHandles[0].hide()
            self._deleteCrossHandles[1].hide()

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

    def update_brush_diameter(self, change):
        val = self.brush_diameter
        val += change
        if val > self.MAX_BRUSH_DIAMETER:
            val = self.MAX_BRUSH_DIAMETER

        if val < self.MIN_BRUSH_DIAMETER:
            val = self.MIN_BRUSH_DIAMETER

        self.brush_diameter = val

        if self._lastCursorCoords is not None:
            x, y = self._lastCursorCoords
        else:
            x, y = 0, 0

        if self._cursorHandle is not None:
            self._cursorHandle.setPos(x - self.brush_diameter / 2, y - self.brush_diameter / 2)
            self._cursorHandle.setRect(0, 0, self.brush_diameter, self.brush_diameter)

        if self._deleteCrossHandles is not None:
            self._deleteCrossHandles[0].setLine(x - self.brush_diameter / (2 * np.sqrt(2)),
                                                y - self.brush_diameter / (2 * np.sqrt(2)),
                                                x + self.brush_diameter / (2 * np.sqrt(2)),
                                                y + self.brush_diameter / (2 * np.sqrt(2)))
            self._deleteCrossHandles[1].setLine(x - self.brush_diameter / (2 * np.sqrt(2)),
                                                y + self.brush_diameter / (2 * np.sqrt(2)),
                                                x + self.brush_diameter / (2 * np.sqrt(2)),
                                                y - self.brush_diameter / (2 * np.sqrt(2)))

    def update_cursor_location(self, event):
        # There's a problem with this cursor that it's too big.
        # self.viewport().setCursor(Qt.CrossCursor)

        scenePos = self.mapToScene(event.pos())
        x, y = scenePos.x(), scenePos.y()

        # Store the coordinates for other operations to use
        self._lastCursorCoords = (x,y)

        if self._cursorHandle is not None:
            self._cursorHandle.setPos(x - self.brush_diameter/2, y - self.brush_diameter/2)

        if self._deleteCrossHandles is not None:
            self._deleteCrossHandles[0].setLine(x - self.brush_diameter / (2 * np.sqrt(2)),
                                                y - self.brush_diameter / (2 * np.sqrt(2)),
                                                x + self.brush_diameter / (2 * np.sqrt(2)),
                                                y + self.brush_diameter / (2 * np.sqrt(2)))
            self._deleteCrossHandles[1].setLine(x - self.brush_diameter / (2 * np.sqrt(2)),
                                                y + self.brush_diameter / (2 * np.sqrt(2)),
                                                x + self.brush_diameter / (2 * np.sqrt(2)),
                                                y - self.brush_diameter / (2 * np.sqrt(2)))

    def redraw_cursor(self):
        if self._cursorHandle is not None:
            self._cursorHandle.update()

        if self._deleteCrossHandles is not None:
            self._deleteCrossHandles[0].update()
            self._deleteCrossHandles[1].update()

    def wheelEvent(self, event):

        if self.hasImage():

            self.redraw_cursor()

            # Depending on whether control is pressed, set brush diameter accordingly
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                change = 1 if event.angleDelta().y() > 0 else -1
                self.update_brush_diameter(change)
                self.redraw_cursor()
                self.mouseWheelRotated.emit(change)
            else:
                QGraphicsView.wheelEvent(self, event)

    def mouseMoveEvent(self, event):

        if self.hasImage():

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

        # TODO: With really large images, update is very slow. Must somehow fix this.
        # It seems that the way to approach hardcore optimization is to switch to OpenGL
        # for all rendering purposes. This update will likely come much later in the tool's
        # lifecycle.
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

    # Fills an area using the last stored cursor location
    def fillArea(self):

        # Store previous state so we can go back to it
        self._overlay_stack.append(self.mask_pixmap.copy())

        # We first convert the mask to a QImage and then to ndarray
        orig_mask = self.mask_pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        msk = alpha_view(orig_mask).copy()

        # Apply simple tresholding and invert the image
        msk[np.where((msk>0))] = 255
        msk = 255-msk

        # Fill the contour
        seed_point = (int(self.lastCursorLocation.x()), int(self.lastCursorLocation.y()))
        msk1 = np.copy(msk)
        cv2.floodFill(msk1, cv2.copyMakeBorder(cv2.bitwise_not(msk), 1, 1, 1, 1, cv2.BORDER_CONSTANT, 0),
                      seed_point, 0, 0, 1)

        # We paint in only the newly arrived pixels
        paintin = msk - msk1

        # Take original pixmap image: it has two components, RGB and ALPHA
        new_img = np.dstack((rgb_view(orig_mask), alpha_view(orig_mask)))

        # Fill the newly created area with current brush color
        new_img[np.where((paintin==255))] = list(self.brush_fill_color.getRgb())

        new_qimg = array2qimage(new_img)
        self.mask_pixmap = QPixmap.fromImage(new_qimg)
        self._overlayHandle.setPixmap(self.mask_pixmap)

    # Keypress event handler
    def keyPressEvent(self, event):

        if self.hasImage():
            if event.key() == Qt.Key_F:
                try:
                    self.viewport().setCursor(Qt.BusyCursor)
                    self.fillArea()
                except:
                    print("Cannot fill region")
                self.viewport().setCursor(Qt.ArrowCursor)

            # Erase mode enable/disable
            if event.key() == Qt.Key_D:
                self.global_erase_override = not self.global_erase_override
                if self.global_erase_override:
                    self.current_painting_mode = self.MODE_ERASE
                    self._deleteCrossHandles[0].show()
                    self._deleteCrossHandles[1].show()
                else:
                    self.current_painting_mode = self.MODE_PAINT
                    self._deleteCrossHandles[0].hide()
                    self._deleteCrossHandles[1].hide()

            # Undo operations
            if event.key() == Qt.Key_Z:
                if QApplication.keyboardModifiers() & Qt.ControlModifier:
                    if (len(self._overlay_stack) > 0):
                        self.mask_pixmap = self._overlay_stack.pop()
                        self._overlayHandle.setPixmap(self.mask_pixmap)
                        self.updateViewer()

            # When CONTROL is pressed, show the delete cross
            if event.key() == Qt.Key_Control and not self.global_erase_override:
                self._deleteCrossHandles[0].show()
                self._deleteCrossHandles[1].show()

        QGraphicsView.keyPressEvent(self, event)

    def keyReleaseEvent(self, event):

        if self.hasImage():

            if event.key() == Qt.Key_Control and not self.global_erase_override:
                self._deleteCrossHandles[0].hide()
                self._deleteCrossHandles[1].hide()

        QGraphicsView.keyPressEvent(self, event)

    def mousePressEvent(self, event):

        if self.hasImage():
            """ Start drawing, panning with mouse, or zooming in
            """
            scenePos = self.mapToScene(event.pos())
            if event.button() == Qt.LeftButton:

                self._overlay_stack.append(self.mask_pixmap.copy())

                # If SHIFT is held, draw a line
                if QApplication.keyboardModifiers() & Qt.ShiftModifier:
                    self.drawMarkerLine(event)

                # If CONTROL is held, erase, but only if global erase override is not enabled
                if not self.global_erase_override:
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
        if self.hasImage():
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
        QGraphicsView.mouseReleaseEvent(self, event)

    def mouseDoubleClickEvent(self, event):
        """ Show entire image.
        """
        if self.hasImage():
            scenePos = self.mapToScene(event.pos())
            if event.button() == Qt.MiddleButton:
                self.middleMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
            elif event.button() == Qt.RightButton:
                if self.canZoom:
                    self.zoomStack = []  # Clear zoom stack.
                    self.updateViewer()
                self.rightMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
        QGraphicsView.mouseDoubleClickEvent(self, event)

    # Export current mask WITHOUT alpha channel (mask types are determined by colors, not by alpha anyway)
    def export_ndarray_noalpha(self):
        mask = self.mask_pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        return rgb_view(mask).copy()

    def export_ndarray(self):
        mask = self.mask_pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        return np.dstack((rgb_view(mask).copy(), alpha_view(mask).copy()))

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
