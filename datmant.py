# Import GUI specific items
from PyQt5 import QtGui, QtWidgets, QtCore
import sys
import traceback
import os
#from lib.ae_backend import ae_backend
import numpy as np
import matplotlib
import pandas as pd
from pandas import Series, DataFrame
import math
import scipy.signal
import shutil
import cv2

matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt

plt.ion()
import matplotlib.patches as patches
from ui import datmant_ui
import configparser
import time
import datetime
import pickle
import subprocess

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

# Overall constants
PUBLISHER = "AlphaControlLab"
VERSION = "1.0"

# Some configs
BRUSH_DIAMETER_MIN = 10
BRUSH_DIAMETER_MAX = 400
BRUSH_DIAMETER_MASK = 2000
BRUSH_DIAMETER_DEFAULT = 100

# Main UI class with all methods
class DATMantGUI(QtWidgets.QMainWindow, datmant_ui.Ui_DATMantMainWindow):
    # Applications states in status bar
    APP_STATUS_STATES = {"ready": "Ready.", "loading": "Loading image..."}

    # Config file
    config_path = None  # Path to config file
    config_data = None  # The actual configuration
    CONFIG_NAME = "datmant_config.cfg"  # Name of the config file

    # Embedded pyplot graph
    figure_view = None
    canvas_view = None
    toolbar_view = None
    axes_view = None

    img_shape = None

    # Drawing mode
    annotation_mode = 0 # 0 for marking defects, 1 for updating mask. Brush will change accordingly

    # We should always know where the cursor is
    curx = 0
    cury = 0

    # Brush
    brush = None
    brush_diameter = BRUSH_DIAMETER_DEFAULT

    # Stored marks
    defect_marks = None
    mask_marks = None

    # Stored background
    canvas_bg = None

    # Image name
    current_img = None

    # Internal vars
    initializing = False
    app = None

    def __init__(self, parent=None):

        self.initializing = True

        # Setting up the base UI
        super(DATMantGUI, self).__init__(parent)
        self.setupUi(self)

        # Config file storage: config file stored in user directory
        self.config_path = self.fix_path(os.path.expanduser("~")) + PUBLISHER + os.sep

        # TODO: TEMP: For buttons, use .clicked.connect(self.*), for menu actions .triggered.connect(self.*),
        # TODO: TEMP: for checkboxes use .stateChanged, and for spinners .valueChanged
        self.actionLog.triggered.connect(self.update_show_log)

        # Button assignment
        self.btnClear.clicked.connect(self.clear_all_annotations)
        self.btnBrowseImageDir.clicked.connect(self.browse_image_directory)
        self.btnPrev.clicked.connect(self.load_prev_image)
        self.btnNext.clicked.connect(self.load_next_image)

        # Update button states
        self.update_button_states()

        # Load configuration
        self.config_load()

        # Add the FigureCanvas
        self.figure_view = Figure()
        self.canvas_view = FigureCanvas(self.figure_view)
        self.toolbar_view = NavigationToolbar(self.canvas_view, self)
        self.figThinFigure.addWidget(self.toolbar_view)
        self.figThinFigure.addWidget(self.canvas_view)

        # Add axes
        self.axes_view = self.figure_view.add_subplot(111)

        # Set tight layout
        self.figure_view.tight_layout()

        # Initialize everything
        self.initialize_brush_slider()
        self.initialize_canvas()

        # Check whether log should be shown or not
        self.check_show_log()

        # Log this anyway
        self.log("Application started")

        # Initialization completed
        self.initializing = False

        # Set up blitting
        # Get background for now only
        self.canvas_view.mpl_connect("resize_event", self.canvas_grab_bg)

        # Save the configuration (takes into account newly added entries, for example)
        self.config_save()

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
        self.update_brush()

    # Initialize canvas: add all the necessary functionality
    def initialize_canvas(self):
        self.canvas_view.mpl_connect('motion_notify_event', self.canvas_mouse_interaction)
        self.canvas_view.mpl_connect('button_press_event', self.canvas_mouse_interaction)

    # Helper function for disabling zoom after zoom event
    def canvas_zoom_changed(self, event=None):
        if self.toolbar_view.mode == "zoom rect":
            self.toolbar_view.zoom()
        self.canvas_grab_bg()

    # Get the correct brush diameter depending on the current mode
    def get_mode_diam(self):
        if self.annotation_mode == 0:
            return self.brush_diameter
        elif self.annotation_mode == 1:
            return BRUSH_DIAMETER_MASK
        else:
            return BRUSH_DIAMETER_DEFAULT

    def update_brush(self):
        # Get the diameter
        set_diam = self.get_mode_diam()

        # Create the brush if it doesn't exist
        if self.brush is None:
            self.brush = self.axes_view.add_patch(
                patches.Circle((self.curx, self.cury), int(set_diam/2), fc="None", ec='black', ls="--"))

        # Make sure all parameters of the brush are updated
        self.brush.set_radius(int(set_diam/2))

    def canvas_mouse_interaction(self, event):
        print(event)

        # Get cursor location
        curx = event.xdata
        cury = event.ydata

        # Stop here if we are outside the image
        if curx is None or cury is None:
            return

        # Otherwise update the coordinates
        self.curx = curx
        self.cury = cury

        # Update brush
        self.update_brush()

        # If we are in pan or resize mode, we stop here
        if self.toolbar_view.mode != "":
            self.brush.set_visible(False)
            return

        # Otherwise we proceed with drawing the brush
        self.brush.set_visible(True)

        # Update brush coordinates
        self.brush.center = (curx, cury)

        # If mouse 1 is pressed, we need to start storing the on canvas paint events
        if event.button == 1:
            # Depends on mode
            if self.annotation_mode == 0:
                if self.defect_marks is None:
                    self.defect_marks = []
                self.defect_marks.append(
                    self.axes_view.add_patch(patches.Circle((self.curx, self.cury),
                                                            int(self.brush_diameter/2), fc=(0,0,1,0.1), ec='None')))

        self.canvas_blit()

    def canvas_grab_bg(self, event=None):
        # Disable all drawable actors
        if self.brush is not None:
            self.brush.set_visible(False)
        if self.defect_marks is not None:
            for dm in self.defect_marks:
                dm.set_visible(False)
        if self.mask_marks is not None:
            for mm in self.mask_marks:
                mm.set_visible(False)

        self.canvas_view.draw()
        self.canvas_bg = self.canvas_view.copy_from_bbox(self.figure_view.bbox)

        # Re-enable drawable actors
        if self.defect_marks is not None:
            for dm in self.defect_marks:
                dm.set_visible(True)
        if self.mask_marks is not None:
            for mm in self.mask_marks:
                mm.set_visible(True)
        if self.brush is not None:
            self.brush.set_visible(True)

        self.canvas_blit()

    def canvas_blit(self):
        self.canvas_view.restore_region(self.canvas_bg)

        # Draw actors that exist
        if self.brush is not None:
            self.axes_view.draw_artist(self.brush)
        if self.defect_marks is not None:
            for dm in self.defect_marks:
                self.axes_view.draw_artist(dm)
        if self.mask_marks is not None:
            for mm in self.mask_marks:
                self.axes_view.draw_artist(mm)

        self.canvas_view.blit(self.figure_view.bbox)

    def clear_all_annotations(self):

        if self.defect_marks is not None:
            for dm in self.defect_marks:
                dm.remove()
        self.defect_marks = None

        if self.mask_marks is not None:
            for mm in self.mask_marks:
                mm.remove()
        self.mask_marks = None

        self.canvas_blit()

    # Debug action: temporary function for doing various tests. Contents change often.
    def load_image(self):

        if not self.initializing:
            self.status_bar_message("loading")

            self.axes_view.clear()
            self.clear_all_annotations()

            # Get the image from the list
            img_name = self.lstImages.currentText()
            img_name_no_ext = img_name.split(".")[0]
            img_path = self.txtImageDir.text() + os.sep + img_name_no_ext

            self.current_img = img_name_no_ext

            # Start loading the image
            self.log("Loading image " + img_name_no_ext)

            # To test we load an image here
            img = cv2.imread(img_path + ".marked.jpg")
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            self.img_shape = img.shape

            # Load the mask as well
            img_m = cv2.imread(img_path + ".cut.mask.png")
            img_m = cv2.bitwise_not(img_m) # Invert mask
            img_m[np.where((img_m == [255, 255, 255]).all(axis=2))] = [255, 0, 0] # Masked area is red

            # Blend the two images
            img_b = cv2.addWeighted(img, 1, img_m, 0.3, 0)

            # Apply to axes
            self.axes_view.imshow(img_b)

            # Set up axes callbacks
            self.axes_view.callbacks.connect("xlim_changed", self.canvas_zoom_changed)
            self.axes_view.callbacks.connect("ylim_changed", self.canvas_zoom_changed)

            self.canvas_view.draw()
            self.canvas_grab_bg()

            self.status_bar_message("ready")
            self.log("Done loading image")

    def load_prev_image(self):
        total_items = self.lstImages.count()
        if total_items == 0:
            return
        cur_index = self.lstImages.currentIndex()
        if cur_index - 1 < 0:
            self.log("This is the first image")
            return
        self.save_masks()
        self.lstImages.setCurrentIndex(cur_index-1)
        self.load_image()

    def load_next_image(self):
        total_items = self.lstImages.count()
        if total_items == 0:
            return
        cur_index = self.lstImages.currentIndex()
        if cur_index+1 == total_items:
            self.log("This is the last image")
            return
        self.save_masks()
        self.lstImages.setCurrentIndex(cur_index + 1)
        self.load_image()

    def save_masks(self):
        save_dir = self.txtImageDir.text()
        save_path = save_dir + self.current_img + ".defect.mask.png"
        if self.defect_marks is not None and len(self.defect_marks) > 0:
            self.log("Saving defect annotation...")
            new_image = np.zeros(self.img_shape, np.uint8)
            for circ in self.defect_marks:
                cv2.circle(new_image, (int(circ.center[0]), int(circ.center[1])), int(circ.radius), (255,255,255),-1)
            cv2.imwrite(save_path, new_image)
            self.log("Saved")

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
            {'ShowLog': '0'}

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
        print("Not implemented")

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

            # Also load the first available image
            self.load_image()

    def update_button_states(self):
        # Here, depending on the loaded config etc decide if we are ready to do the prediction
        print("Not implemented")


def main():
    # Prepare and launch the GUI
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon('res/A.ico'))
    dialog = DATMantGUI()
    dialog.app = app  # Store the reference
    dialog.show()
    app.exec_()


# Run main loop
if __name__ == '__main__':
    # Set the exception hook
    sys.excepthook = traceback.print_exception
    main()
