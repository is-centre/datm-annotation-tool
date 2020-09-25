# Import GUI specific items
from PyQt5 import QtGui, QtWidgets, QtCore
from PyQt5.QtWidgets import QGraphicsView
import sys
import traceback
import os
import numpy as np
import cv2
from qimage2ndarray import array2qimage

from lib.tkmask import generate_tk_defects_layer
from lib.annotmask import get_sqround_mask  # New mask generation facility (original mask needed)

# Specific UI features
from PyQt5.QtWidgets import QSplashScreen, QMessageBox, QGraphicsScene, QFileDialog
from PyQt5.QtGui import QPixmap, QImage, QColor, QIcon
from PyQt5.QtCore import Qt, QRectF, QSize

from ui import datmant_ui
import configparser
import time
import datetime
import subprocess

import pandas as pd

# Overall constants
PUBLISHER = "AlphaControlLab"
APP_TITLE = "DATM Annotation Tool"
APP_VERSION = "1.00.0-beta"

# Some configs
BRUSH_DIAMETER_MIN = 40
BRUSH_DIAMETER_MAX = 100
BRUSH_DIAMETER_DEFAULT = 40

# Colors
MARK_COLOR_MASK = QColor(255,0,0,99)
MARK_COLOR_DEFECT_DEFAULT = QColor(0, 0, 255, 99)
HELPER_COLOR = QColor(0,0,0,99)

# Some paths
COLOR_DEF_PATH = "defs/color_defs.csv"


# Main UI class with all methods
class DATMantGUI(QtWidgets.QMainWindow, datmant_ui.Ui_DATMantMainWindow):
    # Applications states in status bar
    APP_STATUS_STATES = {"ready": "Ready.",
                         "loading": "Loading image...",
                         "exporting_layers": "Exporting layers...",
                         "no_images": "No images or unexpected folder structure."}

    # Annotation modes
    ANNOTATION_MODE_MARKING_DEFECTS = 0
    ANNOTATION_MODE_MARKING_MASK = 1

    ANNOTATION_MODES_BUTTON_TEXT = {ANNOTATION_MODE_MARKING_DEFECTS: "Mode [Marking defects]",
                                    ANNOTATION_MODE_MARKING_MASK: "Mode [Marking mask]"}
    ANNOTATION_MODES_BUTTON_COLORS = {ANNOTATION_MODE_MARKING_DEFECTS: "blue",
                                      ANNOTATION_MODE_MARKING_MASK: "red"}

    # Mask file extension. If it changes in the future, it is easier to swap it here
    MASK_FILE_EXTENSION_PATTERN = ".mask.png"

    # Config file
    config_path = None  # Path to config file
    config_data = None  # The actual configuration
    CONFIG_NAME = "datmant_config.ini"  # Name of the config file

    has_image = None
    img_shape = None

    # Flag which tells whether images were found in CWD
    dir_has_images = False

    # Drawing mode
    annotation_mode = ANNOTATION_MODE_MARKING_DEFECTS

    # Annotator
    annotator = None

    # Brush
    brush = None
    brush_diameter = BRUSH_DIAMETER_DEFAULT

    # Color definitions
    cspec = None

    # For TK
    tk_colors = None

    current_paint = None  # Paint of the brush

    # Color conversion dicts
    d_rgb2gray = None
    d_gray2rgb = None

    # Immutable items
    current_image = None  # Original image
    current_mask = None  # Original mask
    current_helper = None  # Helper mask
    current_tk = None  # Defects mareked by TK

    # User-updatable items
    current_defects = None  # Defects mask
    current_updated_mask = None  # Updated mask

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

        # Need to synchronize brush sizes with the annotator
        self.annotator.MIN_BRUSH_DIAMETER = BRUSH_DIAMETER_MIN
        self.annotator.MAX_BRUSH_DIAMETER = BRUSH_DIAMETER_MAX
        self.annotator.brush_diameter = BRUSH_DIAMETER_DEFAULT

        self.figThinFigure.addWidget(self.annotator)

        # Config file storage: config file stored in user directory
        self.config_path = self.fix_path(os.path.expanduser("~")) + "." + PUBLISHER + os.sep

        # Get color specifications and populate the corresponding combobox
        self.read_defect_color_defs()
        self.add_colors_to_list()

        # Assign necessary dicts in the annotator component
        if self.d_rgb2gray is not None and self.d_gray2rgb is not None:
            self.annotator.d_rgb2gray = self.d_rgb2gray
            self.annotator.d_gray2rgb = self.d_gray2rgb
        else:
            raise RuntimeError("Failed to load the color conversion schemes. Annotations cannot be saved.")

        # Update button states
        self.update_button_states()

        # Initialize everything
        self.initialize_brush_slider()

        # Log this anyway
        self.log("Application started")

        # Style the mode button properly
        self.annotation_mode_default()

        # Initialization completed
        self.initializing = False

        # Set up the status bar
        self.status_bar_message("ready")

    # Set up those UI elements that depend on config
    def UI_config(self):
        # Check whether log should be shown or not
        self.check_show_log()

        # TODO: TEMP: For buttons, use .clicked.connect(self.*), for menu actions .triggered.connect(self.*),
        # TODO: TEMP: for checkboxes use .stateChanged, and for spinners .valueChanged
        self.actionLog.triggered.connect(self.update_show_log)
        self.actionLoad_marked_image.triggered.connect(self.load_image)
        self.actionProcess_original_mask.triggered.connect(self.process_mask)
        self.actionSave_current_annotations.triggered.connect(self.save_masks)

        # Reload AI-generated mask, if present in the directory
        self.actionAIMask.triggered.connect(self.load_AI_mask)

        # Button assignment
        self.annotator.mouseWheelRotated.connect(self.accept_brush_diameter_change)
        self.btnClear.clicked.connect(self.clear_all_annotations)
        self.btnBrowseImageDir.clicked.connect(self.browse_image_directory)
        self.btnBrowseShp.clicked.connect(self.browse_shp_dir)
        self.btnPrev.clicked.connect(self.load_prev_image)
        self.btnNext.clicked.connect(self.load_next_image)
        self.btnMode.clicked.connect(self.annotation_mode_switch)

        # Selecting new image from list
        # NB! We depend on this firing on index change, so we remove manual load_image elsewhere
        self.connect_image_load_on_list_index_change(True)

        # Try to load an image now that everything is initialized
        self.load_image()

    def connect_image_load_on_list_index_change(self, state):
        if state:
            self.lstImages.currentIndexChanged.connect(self.load_image)
        else:
            self.lstImages.disconnect()

    def initialize_brush_slider(self):
        self.sldBrushDiameter.setMinimum(BRUSH_DIAMETER_MIN)
        self.sldBrushDiameter.setMaximum(BRUSH_DIAMETER_MAX)
        self.sldBrushDiameter.setValue(BRUSH_DIAMETER_DEFAULT)
        self.sldBrushDiameter.valueChanged.connect(self.brush_slider_update)
        self.brush_slider_update()

    def brush_slider_update(self):
        new_diameter = self.sldBrushDiameter.value()
        self.txtBrushDiameter.setText(str(new_diameter))
        self.brush_diameter = new_diameter
        self.update_annotator()

    def accept_brush_diameter_change(self, change):

        # Need to disconnect slider while changing value
        self.sldBrushDiameter.valueChanged.disconnect()

        new_diameter = int(self.sldBrushDiameter.value()+change)
        new_diameter = BRUSH_DIAMETER_MIN if new_diameter < BRUSH_DIAMETER_MIN else new_diameter
        new_diameter = BRUSH_DIAMETER_MAX if new_diameter > BRUSH_DIAMETER_MAX else new_diameter
        self.sldBrushDiameter.setValue(new_diameter)
        self.txtBrushDiameter.setText(str(new_diameter))

        # Reconnect to slider move interrupt
        self.sldBrushDiameter.valueChanged.connect(self.brush_slider_update)

    # Clear currently used paint completely
    def clear_all_annotations(self):

        img_new = np.zeros(self.img_shape, dtype=np.uint8)
        if self.annotation_mode is self.ANNOTATION_MODE_MARKING_DEFECTS:
            self.current_defects = img_new
        elif self.annotation_mode is self.ANNOTATION_MODE_MARKING_MASK:
            self.current_updated_mask = 255-img_new
        self.update_annotator_view()
        self.annotator.setFocus()

    def update_annotator(self):
        if self.annotator is not None:
            self.annotator.brush_diameter = self.brush_diameter
            self.annotator.update_brush_diameter(0)
            self.annotator.brush_fill_color = self.current_paint

    def update_mask_from_current_mode(self):
        the_mask = self.get_updated_mask()
        if self.annotation_mode is self.ANNOTATION_MODE_MARKING_DEFECTS:
            self.current_defects = the_mask
        else:
            self.current_updated_mask = the_mask

    # Change annotation mode
    def annotation_mode_switch(self):

        # Save the mask
        self.update_mask_from_current_mode()

        # Update the UI
        self.annotation_mode += 1
        if self.annotation_mode > 1:
            self.annotation_mode = 0
        self.current_paint = [MARK_COLOR_DEFECT_DEFAULT, MARK_COLOR_MASK][self.annotation_mode]
        if self.annotation_mode == self.ANNOTATION_MODE_MARKING_DEFECTS:  # TODO: this should be optimized
            self.change_brush_color()
            self.lstDefectsAndColors.setEnabled(True)
        else:
            self.lstDefectsAndColors.setEnabled(False)
        self.update_annotator()
        self.btnMode.setText(self.ANNOTATION_MODES_BUTTON_TEXT[self.annotation_mode])
        self.btnMode.setStyleSheet("QPushButton {font-weight: bold; color: "
                                   + self.ANNOTATION_MODES_BUTTON_COLORS[self.annotation_mode] + "}")

        # Update the view
        self.update_annotator_view()
        self.annotator.setFocus()

    # Set default annotation mode
    def annotation_mode_default(self):
        self.annotation_mode = self.ANNOTATION_MODE_MARKING_DEFECTS
        self.current_paint = [MARK_COLOR_DEFECT_DEFAULT, MARK_COLOR_MASK][self.annotation_mode]
        if self.annotation_mode == self.ANNOTATION_MODE_MARKING_DEFECTS:
            self.change_brush_color()
            self.lstDefectsAndColors.setEnabled(True)
        else:
            self.lstDefectsAndColors.setEnabled(False)
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
    def get_updated_mask(self):
        if self.annotator._overlayHandle is not None:

            # Depending on the mode, fill the mask appropriately

            # Marking defects
            if self.annotation_mode is self.ANNOTATION_MODE_MARKING_DEFECTS:
                self.status_bar_message("exporting_layers")
                self.log("Exporting color layers...")
                the_new_mask = self.annotator.export_rgb2gray_mask()  # Easy, as this is implemented in annotator
                self.status_bar_message("ready")

            # Or updating the road edge mask
            else:
                mask = self.annotator.export_ndarray_noalpha()
                the_new_mask = 255 * np.ones(self.img_shape, dtype=np.uint8)

                # NB! This approach beats np.where: it is 4.3 times faster!
                reds, greens, blues = mask[:, :, 0], mask[:, :, 1], mask[:, :, 2]

                # Set the mask according to the painted road mask
                m1 = list(MARK_COLOR_MASK.getRgb())[:-1]
                the_new_mask[(reds == m1[0]) & (greens == m1[1]) & (blues == m1[2])] = 0

            return the_new_mask

    def update_annotator_view(self):

        # If there is no image, there's nothing to clear
        if self.current_image is None:
            return

        if self.annotation_mode is self.ANNOTATION_MODE_MARKING_DEFECTS:
            h, w = self.current_image.rect().height(), self.current_image.rect().width()

            helper = np.zeros((h,w,4), dtype=np.uint8)
            helper[self.current_helper == 0] = list(HELPER_COLOR.getRgb())

            self.annotator.clearAndSetImageAndMask(self.current_image,
                                                   self.current_defects,
                                                   array2qimage(helper),
                                                   aux_helper=(array2qimage(self.current_tk) if self.actionLoad_marked_image.isChecked() else None),
                                                   process_gray2rgb=True,
                                                   direct_mask_paint=True)
        else:

            # Remember, the mask must be inverted here, but saved properly
            h, w = self.current_image.rect().height(), self.current_image.rect().width()
            mask = 255 * np.zeros((h, w, 4), dtype=np.uint8)
            mask[self.current_updated_mask == 0] = list(MARK_COLOR_MASK.getRgb())

            self.annotator.clearAndSetImageAndMask(self.current_image,
                                                   mask)

    def process_mask(self):

        # Check the state of the checkbox and save it
        proc_mask = '0'
        if self.actionProcess_original_mask.isChecked():
            proc_mask = '1'
        self.config_data['MenuOptions']['ProcessMask'] == proc_mask
        self.config_save()

        # Now, reload the image
        self.load_image()

    # Loads the image
    def load_image(self):

        if not self.initializing and self.dir_has_images:
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

            # Load the image; if we must add some previous annotation to the image, try to do it here
            if self.actionLoad_marked_image.isChecked():
                try:
                    self.log("Drawing defect marks on original image...")
                    self.current_image = QImage(img_path + ".jpg")
                    img_tk = generate_tk_defects_layer(self.txtImageDir.text(), self.txtShpDir.text(),
                                                    img_name_no_ext, self.tk_colors)
                    self.current_tk = img_tk
                except Exception as e:
                    self.actionLoad_marked_image.setChecked(False)
                    self.log("Could not find or load the shapefile data. Will load the original image instead.")
                    self.current_image = QImage(img_path + ".jpg")
            else:
                self.current_image = QImage(img_path + ".jpg")

            # Shape of the image
            h, w = self.current_image.rect().height(), self.current_image.rect().width()

            self.img_shape = (h,w)

            # Load the mask and generate the "helper" mask
            try:
                self.current_mask = cv2.imread(img_path + self.MASK_FILE_EXTENSION_PATTERN, cv2.IMREAD_GRAYSCALE)
                self.current_helper = get_sqround_mask(self.current_mask)
            except:
                print("Cannot find the mask file. Please make sure FILENAME.mask.png " +
                      "files exist in the folder for every image")
                self.log("Cannot find the mask file. Please make sure FILENAME.mask.png files exist in the folder for every image")
                self.status_bar_message("no_images")
                return

            # Set also default annotation mode
            self.annotation_mode_default()

            # Mask v2 just contains a copy of the default mask
            img_m = self.current_mask.copy()

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

            # No defect marks by default
            img_d = np.zeros(self.img_shape, dtype=np.uint8)
            if os.path.isfile(img_path + ".defect.mask.png"):
                # We need to open the mask
                img_d = cv2.imread(img_path + ".defect.mask.png", cv2.IMREAD_GRAYSCALE)
                # And blend in the colors of the overlay
                self.txtImageStatus.setText("MANUALLY PROCESSED, defect mask found in directory")
            elif os.path.isfile(img_path + ".predicted_defects.png"):
                img_d = cv2.imread(img_path + ".predicted_defects.png", cv2.IMREAD_GRAYSCALE)
                self.txtImageStatus.setText("AUTO PROCESSED, defect mask found in directory")
            elif at_least_something:
                self.txtImageStatus.setText("SEEN BEFORE, but there is no defect mask")
            else:
                self.txtImageStatus.setText("No info")

            # Update a button state
            if os.path.isfile(img_path + ".predicted_defects.png"):
                self.actionAIMask.setEnabled(True)
            else:
                self.actionAIMask.setEnabled(False)

            # Now we set up the mutable images. NB! They are not COPIES, but references here
            self.current_defects = img_d
            self.current_updated_mask = img_m

            # Once all that is done, we need to update the actual image working area
            self.update_annotator_view()

            # Need to set focus on the QGraphicsScene so that shortcuts would work immediately
            self.annotator.setFocus()

            self.status_bar_message("ready")
            self.log("Done loading image")

    def load_AI_mask(self):
        # Additional check just in case
        img_name = self.lstImages.currentText()
        img_name_no_ext = img_name.split(".")[0]
        img_path = self.txtImageDir.text() + os.sep + img_name_no_ext
        if os.path.isfile(img_path + ".predicted_defects.png") and \
                self.annotation_mode is self.ANNOTATION_MODE_MARKING_DEFECTS:
            img_d = cv2.imread(img_path + ".predicted_defects.png", cv2.IMREAD_GRAYSCALE)
            self.current_defects = img_d
            self.update_annotator_view()
            self.log("Replaced the current defect mask with the automatically generated one.")
        else:
            self.log("Cannot load the auto-generated image: either file missing or wrong mode selected.")
            # For now also print it to CMD, maybe remove later
            print("Cannot load the auto-generated image: either file missing eror wrong mode selected.")

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

        # Update the current mask
        self.update_mask_from_current_mode()

        save_dir = self.txtImageDir.text()
        save_path_defects = save_dir + self.current_img + ".defect.mask.png"
        save_path_masks = save_dir + self.current_img + ".cut.mask_v2.png"

        cv2.imwrite(save_path_defects, self.current_defects)
        self.log("Saved defect annotations for image " + self.current_img)

        cv2.imwrite(save_path_masks, self.current_updated_mask)
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

            if self.config_data['MenuOptions']['ProcessMask'] == '1':
                self.actionProcess_original_mask.setChecked(True)
            else:
                self.actionProcess_original_mask.setChecked(False)

            # Get file list, if a URL was saved
            directory = self.config_data['MenuOptions']['ImageDirectory']
            if directory != "":
                self.log('Changed working directory to ' + directory)
                self.txtImageDir.setText(directory)
                self.get_image_files()

            shpdir = self.config_data['MenuOptions']['ShapefileDirectory']
            if shpdir != "":
                self.log('Changed shapefile directory to ' + shpdir)
                self.txtShpDir.setText(shpdir)

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
             'ProcessMask': '1',
             'ImageDirectory': '',
             'ShapefileDirectory': ''}

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
        self.txtShpDir.setText(self.fix_path(self.txtShpDir.text()))

    def store_paths_to_config(self):
        # Use this to store the paths to config
        self.config_data['MenuOptions']['ImageDirectory'] = self.txtImageDir.text()
        self.config_data['MenuOptions']['ShapefileDirectory'] = self.txtShpDir.text()
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

    # Locate the shapefile directory
    def browse_shp_dir(self):
        dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose directory containing the defect shapefiles")

        if dir:

            self.txtShpDir.setText(dir)
            self.check_paths()
            self.store_paths_to_config()

            self.log('Changed defect shapefile directory to ' + dir)


    # Locate working directory with files
    def browse_image_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose working directory")
        if directory:

            ##### Clear the annotator
            self.current_image = None  # Original image
            self.current_mask = None  # Original mask
            self.current_helper = None  # Helper mask
            self.clear_all_annotations()

            # User-updatable items
            self.current_defects = None  # Defects mask
            self.current_updated_mask = None  # Updated mask

            # Image name
            self.current_img = None
            self.current_img_as_listed = None

            self.annotator.clearAll()

            #####

            # Set the path
            self.txtImageDir.setText(directory)
            self.check_paths()
            self.store_paths_to_config()

            self.log('Changed working directory to ' + directory)

            self.get_image_files()

            # Disable the index change event, load image, reenable it
            self.connect_image_load_on_list_index_change(False)
            self.load_image()
            self.connect_image_load_on_list_index_change(True)

    def get_image_files(self):
        directory = self.txtImageDir.text()

        if os.path.isdir(directory):

            # Get the JPG files
            self.lstImages.clear()
            allowed_ext = [".jpg"]
            file_cnt = 0
            for file_name in os.listdir(directory):
                if any(ext in file_name.lower() for ext in allowed_ext) and file_name.count(".") < 2:
                    file_cnt += 1
                    self.lstImages.addItem(os.path.splitext(file_name)[0])

            if file_cnt > 0:
                self.dir_has_images = True
            else:
                self.dir_has_images = False

            self.log("Found " + str(file_cnt) + " images in the working directory")

    def update_button_states(self):  # TODO: Reserved for future use
        return

    def read_defect_color_defs(self):  # Read the defect color definitions from the corresponding file
        # Read the file
        cspec = pd.read_csv(COLOR_DEF_PATH,
                            delimiter=";", encoding='utf-8')
        cspec_list = cspec.to_dict('records')

        # Store the list
        self.cspec = cspec_list

    def add_colors_to_list(self):
        if self.cspec is not None:

            # Remove index change, if it is defined
            try:
                self.lstDefectsAndColors.disconnect()
            except:
                pass  # Do nothing, just a precaution

            # Create the necessary dicts
            g2rgb = {}
            rgb2g = {}
            tk2rgb = {}

            for col in self.cspec:
                rgb_val = col["COLOR_HEXRGB_DATMANT"].lower()
                g_val = int(col["COLOR_GSCALE_MAPPING"])

                keys_to_insert = col["COLOR_ABBR_ET"].split(",")
                for ks in keys_to_insert:
                    tk2rgb[ks.strip()] = col["COLOR_HEXRGB_TK"]

                # Create the icon and populate the list
                pix = QPixmap(50, 50)
                pix.fill(QColor(rgb_val))
                ticon = QIcon(pix)
                self.lstDefectsAndColors.addItem(ticon, " " + col["COLOR_NAME_EN"] +
                                                 " | " + col["COLOR_NAME_ET"])

                # Fill in necessary dicts
                g2rgb[g_val] = rgb_val
                rgb2g[rgb_val] = g_val

            # Set up dicts
            self.d_rgb2gray = rgb2g
            self.d_gray2rgb = g2rgb
            self.tk_colors = tk2rgb

            # Change the brush color
            self.lstDefectsAndColors.currentIndexChanged.connect(self.change_brush_color)

        else:
            self.log("Cannot add colors to the list, specification missing")

    def change_brush_color(self):
        cind = self.lstDefectsAndColors.currentIndex()
        color = self.cspec[cind]
        the_color = QColor("#63" + color["COLOR_HEXRGB_DATMANT"].split("#")[1])
        self.current_paint = the_color
        self.annotator.brush_fill_color = the_color


def main():
    # Prepare and launch the GUI
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon('res/A.ico'))
    dialog = DATMantGUI()
    dialog.setWindowTitle(APP_TITLE + " - " + APP_VERSION) # Window title
    dialog.app = app  # Store the reference
    dialog.show()

    # Now we have to load the app configuration file
    dialog.config_load()

    # After loading the config file, we need to set up relevant UI elements
    dialog.UI_config()
    dialog.app.processEvents()

    # Now we also save the config file
    dialog.config_save()

    # And proceed with execution
    app.exec_()


# Run main loop
if __name__ == '__main__':
    # Set the exception hook
    sys.excepthook = traceback.print_exception
    main()
