# Import GUI specific items
from PyQt5 import QtGui, QtWidgets, QtCore
from PyQt5.QtWidgets import QGraphicsView
import sys
import traceback
import os
import numpy as np
import cv2
from qimage2ndarray import array2qimage

# Specific UI features
from PyQt5.QtWidgets import QSplashScreen, QMessageBox, QGraphicsScene, QFileDialog
from PyQt5.QtGui import QPixmap, QImage, QColor
from PyQt5.QtCore import Qt, QRectF

from ui import datmant_ui
import configparser
import time
import datetime
import subprocess

# Overall constants
PUBLISHER = "AlphaControlLab"
VERSION = "1.0"

# Some configs
BRUSH_DIAMETER_MIN = 1
BRUSH_DIAMETER_MAX = 500
BRUSH_DIAMETER_DEFAULT = 50

# Colors
MARK_COLOR_MASK = QColor(255,0,0,99)
MARK_COLOR_DEFECT = QColor(0,0,255,99)

# Main UI class with all methods
class DATMantGUI(QtWidgets.QMainWindow, datmant_ui.Ui_DATMantMainWindow):
    # Applications states in status bar
    APP_STATUS_STATES = {"ready": "Ready.", "loading": "Loading image..."}

    # Annotation modes
    ANNOTATION_MODES_BUTTON_TEXT = {0: "Mode [Marking defects]", 1: "Mode [Marking mask]"}
    ANNOTATION_MODES_BUTTON_COLORS = {0: "blue", 1: "red"}

    # Mask file extension. If it changes in the future, it is easier to swap it here
    MASK_FILE_EXTENSION_PATTERN = ".mask.png"

    # Config file
    config_path = None  # Path to config file
    config_data = None  # The actual configuration
    CONFIG_NAME = "datmant_config.ini"  # Name of the config file

    # Embedded pyplot graph
    figure_view = None
    canvas_view = None
    toolbar_view = None
    axes_view = None

    has_image = None
    img_shape = None

    # Drawing mode
    annotation_mode = 0 # 0 for marking defects, 1 for updating mask

    # Annotator
    annotator = None

    # We should always know where the cursor is
    curx = 0
    cury = 0

    # Brush
    brush = None
    brush_diameter = BRUSH_DIAMETER_DEFAULT

    current_paint = None

    # Stored marks
    defect_marks = None
    mask_marks = None

    # Stored background
    canvas_bg = None

    # Stored original mask
    current_mask = None

    # Image name
    current_img = None
    current_img_as_listed = None

    # Internal vars
    initializing = False
    app = None

    def __init__(self, parent=None):

        self.initializing = True

        # Setting up the base UI
        super(DATMantGUI, self).__init__(parent)
        self.setupUi(self)

        from ui_lib.QtImageAnnotator import QtImageAnnotator
        self.annotator = QtImageAnnotator()
        self.figThinFigure.addWidget(self.annotator)

        # Config file storage: config file stored in user directory
        self.config_path = self.fix_path(os.path.expanduser("~")) + "." + PUBLISHER + os.sep

        # TODO: TEMP: For buttons, use .clicked.connect(self.*), for menu actions .triggered.connect(self.*),
        # TODO: TEMP: for checkboxes use .stateChanged, and for spinners .valueChanged
        self.actionLog.triggered.connect(self.update_show_log)
        self.actionLoad_marked_image.triggered.connect(self.load_image)
        self.actionSave_current_annotations.triggered.connect(self.save_masks)

        # Button assignment
        self.annotator.mouseWheelRotated.connect(self.accept_brush_diameter_change)
        self.btnClear.clicked.connect(self.clear_all_annotations)
        self.btnBrowseImageDir.clicked.connect(self.browse_image_directory)
        self.btnPrev.clicked.connect(self.load_prev_image)
        self.btnNext.clicked.connect(self.load_next_image)
        self.btnMode.clicked.connect(self.annotation_mode_switch)

        # Selecting new image from list
        # NB! We depend on this firing on index change, so we remove manual load_image elsewhere
        self.lstImages.currentIndexChanged.connect(self.load_image)

        # Update button states
        self.update_button_states()

        # Initialize everything
        self.initialize_brush_slider()

        # Check whether log should be shown or not
        self.check_show_log()

        # Log this anyway
        self.log("Application started")

        # Style the mode button properly
        self.annotation_mode_default()

        # Initialization completed
        self.initializing = False

        # Set up the status bar
        self.status_bar_message("ready")

    def initialize_brush_slider(self):
        self.sldBrushDiameter.setMinimum(BRUSH_DIAMETER_MIN)
        self.sldBrushDiameter.setMaximum(BRUSH_DIAMETER_MAX)
        self.sldBrushDiameter.setValue(BRUSH_DIAMETER_DEFAULT)
        self.sldBrushDiameter.sliderMoved.connect(self.brush_slider_update)
        self.brush_slider_update()

    def brush_slider_update(self):
        new_diameter = self.sldBrushDiameter.value()
        self.txtBrushDiameter.setText(str(new_diameter))
        self.brush_diameter = new_diameter
        self.update_annotator()

    def accept_brush_diameter_change(self, change):

        # Need to disconnect slider while changing value
        self.sldBrushDiameter.sliderMoved.disconnect()

        new_diameter = int(self.sldBrushDiameter.value()+change)
        new_diameter = BRUSH_DIAMETER_MIN if new_diameter < BRUSH_DIAMETER_MIN else new_diameter
        new_diameter = BRUSH_DIAMETER_MAX if new_diameter > BRUSH_DIAMETER_MAX else new_diameter
        self.sldBrushDiameter.setValue(new_diameter)
        self.txtBrushDiameter.setText(str(new_diameter))

        # Reconnect to slider move interrupt
        self.sldBrushDiameter.sliderMoved.connect(self.brush_slider_update)

    # Clear currently used paint completely
    def clear_all_annotations(self):

        print("Not implemented")

    def update_annotator(self):
        if self.annotator is not None:
            self.annotator.brush_diameter = self.brush_diameter
            self.annotator.update_brush_diameter(0)
            self.annotator.brush_fill_color = self.current_paint

    # Change annotation mode
    def annotation_mode_switch(self):
        self.annotation_mode += 1
        if self.annotation_mode > 1:
            self.annotation_mode = 0
        self.current_paint = [MARK_COLOR_DEFECT, MARK_COLOR_MASK][self.annotation_mode]
        self.update_annotator()
        self.btnMode.setText(self.ANNOTATION_MODES_BUTTON_TEXT[self.annotation_mode])
        self.btnMode.setStyleSheet("QPushButton {font-weight: bold; color: "
                                   + self.ANNOTATION_MODES_BUTTON_COLORS[self.annotation_mode] + "}")

    # Set default annotation mode
    def annotation_mode_default(self):
        self.annotation_mode = 0
        self.current_paint = [MARK_COLOR_DEFECT, MARK_COLOR_MASK][self.annotation_mode]
        self.update_annotator()
        self.btnMode.setText(self.ANNOTATION_MODES_BUTTON_TEXT[self.annotation_mode])
        self.btnMode.setStyleSheet("QPushButton {font-weight: bold; color: "
                                   + self.ANNOTATION_MODES_BUTTON_COLORS[self.annotation_mode] + "}")

    # Helper for QMessageBox
    def show_info_box(self, title, text):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText(text)
        msg.setWindowTitle(title)
        msg.setModal(True)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    # Get both masks as separate numpy arrays
    def get_updated_masks(self):
        if self.annotator._overlayHandle is not None:

            # Get the overall mask
            mask = self.annotator.export_ndarray_noalpha()

            # And create empty masks
            update_mask = 255*np.ones(self.img_shape, dtype=np.uint8)
            defect_mask = np.zeros(self.img_shape, dtype=np.uint8)

            # NB! This approach beats np.where: it is 4.3 times faster!
            reds, greens, blues = mask[:, :, 0], mask[:, :, 1], mask[:, :, 2]

            m1 = list(MARK_COLOR_MASK.getRgb())[:-1]
            update_mask[(reds == m1[0]) & (greens == m1[1]) & (blues == m1[2])] = 0

            m2 = list(MARK_COLOR_DEFECT.getRgb())[:-1]
            defect_mask[(reds == m2[0]) & (greens == m2[1]) & (blues == m2[2])] = 255

            return update_mask, defect_mask

    # Loads the image
    def load_image(self):

        if not self.initializing:
            self.status_bar_message("loading")

            # Process events
            self.app.processEvents()

            # Get the image from the list
            img_name = self.lstImages.currentText()
            img_name_no_ext = img_name.split(".")[0]
            img_path = self.txtImageDir.text() + os.sep + img_name_no_ext

            self.current_img = img_name_no_ext
            self.current_img_as_listed = img_name

            # Start loading the image
            self.log("Loading image " + img_name_no_ext)

            # To test we load an image here
            img = QImage(img_path + (".jpg", ".marked.jpg")[self.actionLoad_marked_image.isChecked()])

            # Shape of the image
            h, w = img.rect().height(), img.rect().width()

            self.img_shape = (h,w)

            # Load the mask as well
            try:
                img_m = cv2.imread(img_path + self.MASK_FILE_EXTENSION_PATTERN, cv2.IMREAD_GRAYSCALE)
            except:
                self.log("No mask is found for the image. The mask will be empty")
                img_m = np.zeros((h,w,1), dtype=np.uint8)

            # We need to create the empty pixmap and then add correct colors to it thus
            # creating a blended image of the masks
            img_b = np.zeros((h,w,4), dtype=np.uint8)

            # Set also default annotation mode
            self.annotation_mode_default()

            # Add some useful information
            at_least_something = False
            if os.path.isfile(img_path + ".cut.mask_v2.png"):
                # Image has updated defect mask, need to load it instead
                img_m = cv2.imread(img_path + ".cut.mask_v2.png", cv2.IMREAD_GRAYSCALE)
                self.log("Detected updated mask, loading it instead of base mask")
                self.txtImageHasDefectMask.setText("YES")
                at_least_something = True
            else:
                self.txtImageHasDefectMask.setText("NO")

            img_b[img_m == 0] = list(MARK_COLOR_MASK.getRgb())

            if os.path.isfile(img_path + ".defect.mask.png"):
                # We need to open the mask
                img_d = cv2.imread(img_path + ".defect.mask.png", cv2.IMREAD_GRAYSCALE)
                # And blend in the colors of the overlay
                img_b[img_d == 255] = list(MARK_COLOR_DEFECT.getRgb())
                self.txtImageStatus.setText("PROCESSED, defect mask found in directory")
            elif at_least_something:
                self.txtImageStatus.setText("SEEN BEFORE, but there is no defect mask")
            else:
                self.txtImageStatus.setText("No info")

            # Once all that is done, we need to convert the mask to a qimage and update the viewport
            self.annotator.clearAndSetImageAndMask(img, array2qimage(img_b))

            self.status_bar_message("ready")
            self.log("Done loading image")

    def load_prev_image(self):
        total_items = self.lstImages.count()
        if total_items == 0:
            return
        cur_index = self.lstImages.currentIndex()
        if cur_index - 1 < 0:
            self.log("This is the first image. Saving annotation masks.")
            self.show_info_box("First image",
                               "This is the first image in the folder. I will now save the current annotation masks.")
            self.save_masks()
            return
        self.save_masks()
        self.lstImages.setCurrentIndex(cur_index-1)

    def load_next_image(self):
        total_items = self.lstImages.count()
        if total_items == 0:
            return
        cur_index = self.lstImages.currentIndex()
        if cur_index+1 == total_items:
            self.log("This is the last image")
            self.show_info_box("Last image",
                               "This is the last image in the folder. I will now save the current annotation masks.")
            self.save_masks()
            return
        self.save_masks()
        self.lstImages.setCurrentIndex(cur_index + 1)

    def save_masks(self):
        save_dir = self.txtImageDir.text()
        save_path_defects = save_dir + self.current_img + ".defect.mask.png"
        save_path_masks = save_dir + self.current_img + ".cut.mask_v2.png"

        m1, m2 = self.get_updated_masks()
        cv2.imwrite(save_path_defects, m2)
        self.log("Saved defect annotations for image " + self.current_img)

        cv2.imwrite(save_path_masks, m1)
        self.log("Saved updated mask for image " + self.current_img)

    # In-GUI console log
    def log(self, line):
        # Get the time stamp
        ts = datetime.datetime.fromtimestamp(time.time()).strftime('[%Y-%m-%d %H:%M:%S] ')
        self.txtConsole.moveCursor(QtGui.QTextCursor.End)
        self.txtConsole.insertPlainText(ts + line + os.linesep)

        # Only do this if app is already referenced in the GUI (TODO: a more elegant solution?)
        if self.app is not None:
            self.app.processEvents()

    def check_show_log(self):
        if self.actionLog.isChecked():
            self.gbApplicationLog.show()
        else:
            self.gbApplicationLog.hide()

    def update_show_log(self):
        self.check_show_log()
        self.store_menu_options_to_config()

    @staticmethod
    def open_file_in_os(fn):
        if sys.platform == "win32":
            os.startfile(fn)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.call([opener, fn])

    # Path related functions
    @staticmethod
    def fix_path(p):
        # Only if string is nonempty
        if len(p) > 0:
            p = p.replace("/", os.sep).replace("\\", os.sep)
            p = p + os.sep if p[-1:] != os.sep else p
            return p

    @staticmethod
    def fix_file_path(p):
        # Only if string is nonempty
        if len(p) > 0:
            p = p.replace("/", os.sep).replace("\\", os.sep)
            return p

    # The following methods deal with config files
    def config_load(self):
        # First check if the file exists there, if not, create it
        if os.path.isfile(self.config_path + self.CONFIG_NAME):

            # Read data back from the config file and set it up in the GUI
            config = configparser.ConfigParser()
            config.read(self.config_path + self.CONFIG_NAME)

            # Before we proceed, we must ensure that all sections and options are present
            config = self.check_config(config)

            self.config_data = config

            # Set menu options
            if self.config_data['MenuOptions']['ShowLog'] == '1':
                self.actionLog.setChecked(True)
            else:
                self.actionLog.setChecked(False)

            # Get file list, if a URL was saved
            directory = self.config_data['MenuOptions']['ImageDirectory']
            if directory != "":
                self.log('Changed working directory to ' + directory)
                self.txtImageDir.setText(directory)
                self.get_image_files()

        else:

            # Initialize the config file
            self.config_init()

    def config_save(self):
        # If file exists (it should by now) and app initialization is finished, store new parameters
        if os.path.isfile(self.config_path + self.CONFIG_NAME) and not self.initializing:
            with open(self.config_path + self.CONFIG_NAME, 'w') as configFile:
                self.config_data.write(configFile)

    @staticmethod
    def config_defaults():

        # Dictionary
        config_defaults = {}

        # The defaults
        config_defaults['MenuOptions'] = \
            {'ShowLog': '0',
             'ImageDirectory': ''}

        return config_defaults

    def check_config(self, config):

        # Load the defaults and check whether the config has all the options
        defs = self.config_defaults()
        secs = list(defs.keys())

        # Now go item by item and add those that are missing
        for k in range(len(secs)):
            opns = list(defs[secs[k]].keys())

            # Make sure corresponding section exists
            if not config.has_section(secs[k]):
                config.add_section(secs[k])

            # And check all the options as well
            for m in range(len(opns)):
                if not config.has_option(secs[k],opns[m]):
                    config[secs[k]][opns[m]] = str(defs[secs[k]][opns[m]])

        return config

    def config_init(self):
        os.makedirs(self.config_path, exist_ok=True)  # Create the directory if needed
        config = configparser.ConfigParser()

        # Set the default configs
        the_defs = self.config_defaults()
        secs = list(the_defs.keys())
        for k in range(len(secs)):
            opns = list(the_defs[secs[k]].keys())
            config.add_section(secs[k])
            for m in range(len(opns)):
                config[secs[k]][opns[m]] = str(the_defs[secs[k]][opns[m]])

        with open(self.config_path + self.CONFIG_NAME, 'w') as configFile:
            config.write(configFile)

        self.config_data = config

    def check_paths(self):
        # Use this to check the paths
        self.txtImageDir.setText(self.fix_path(self.txtImageDir.text()))

    def store_paths_to_config(self):
        # Use this to store the paths to config
        self.config_data['MenuOptions']['ImageDirectory'] = self.txtImageDir.text()
        self.config_save()

    def store_menu_options_to_config(self):
        if not self.initializing:

            # Logging
            the_log = '0'
            if self.actionLog.isChecked():
                the_log = '1'
            self.config_data['MenuOptions']['ShowLog'] = the_log
            self.config_save()

    # Show different messages in status bar
    def status_bar_message(self, msgid):
        self.statusbar.showMessage(self.APP_STATUS_STATES[msgid])
        if self.app is not None:
            self.app.processEvents()

    # Locate working directory with files
    def browse_image_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose working directory")
        if directory:
            # Set the path
            self.txtImageDir.setText(directory)
            self.check_paths()
            self.store_paths_to_config()

            self.log('Changed working directory to ' + directory)

            self.get_image_files()

    def get_image_files(self):
        directory = self.txtImageDir.text()

        if os.path.isdir(directory):

            # Get the JPG files
            self.lstImages.clear()
            allowed_ext = ".marked.jpg"
            disallowed_ext = ".cut.marked.jpg"
            file_cnt = 0
            for file_name in os.listdir(directory):
                if allowed_ext in file_name and disallowed_ext not in file_name:
                    file_cnt += 1
                    self.lstImages.addItem(os.path.splitext(file_name)[0])

            self.log("Found " + str(file_cnt) + " images in the working directory")

    def update_button_states(self):
        print("Not implemented")


def main():
    # Prepare and launch the GUI
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon('res/A.ico'))
    dialog = DATMantGUI()
    dialog.app = app  # Store the reference
    dialog.show()

    # Now we have to load the app configuration file
    dialog.config_load()

    # And proceed with execution
    app.exec_()


# Run main loop
if __name__ == '__main__':
    # Set the exception hook
    sys.excepthook = traceback.print_exception
    main()
