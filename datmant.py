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


# Main UI class with all methods
class DATMantGUI(QtWidgets.QMainWindow, datmant_ui.Ui_DATMantMainWindow):
    # Applications states in status bar
    APP_STATUS_STATES = {"ready": "Ready."}

    # Config file
    config_path = None  # Path to config file
    config_data = None  # The actual configuration
    CONFIG_NAME = "datmant_config.cfg"  # Name of the config file

    # Embedded pyplot graph
    figure_view = None
    canvas_view = None
    toolbar_view = None
    axes_view = None

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

        # Check whether log should be shown or not
        self.check_show_log()

        # Log this anyway
        self.log("Application started")

        # Initialization completed
        self.initializing = False

        # Save the configuration (takes into account newly added entries, for example)
        self.config_save()

        # Set up the status bar
        self.status_bar_message("ready")

    # Debug action: temporary function for doing various tests. Contents change often.
    def debug_action(self):
        # This will currently load up the temp data into a pandas dataframe and plot 24 hours of some random day
        df = pd.read_csv(self.TEMP_PATH, sep=';', decimal=',')
        df.set_index('date', inplace=True)  # Set the correct indexing
        df.index = pd.to_datetime(df.index)  # Make sure we are actually dealing with datetime format here
        s = df['residential']  # This creates a time series based on residential power consumption

        if not self.initializing:
            # Do a plot of residential consumption for some date as an example
            # E.g., 2017-10-01.
            self.axes_view.clear()

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
        print("Not implemented")

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

    def browse_data_file(self):
        the_file = QtWidgets.QFileDialog.getOpenFileName(self, "Choose the points shapefile")
        if the_file:
            # Set the path
            # SET THE TEXT HERE self.txt.setText(the_file[0])
            self.check_paths()
            self.store_paths_to_config()
            self.log('Will use the camera points from shapefile ' + the_file[0] + ' for pavement extraction.')

    # Locate working directory with files
    def browse_working_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose working directory")
        if directory:
            # Set the path
            self.txtWorkingDirectory.setText(directory)
            self.check_paths()
            self.store_paths_to_config()

            self.log('Changed working directory to ' + directory)

            self.get_image_files()

    # Locate working directory with defect files
    def browse_output_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose directory to store output files")
        if directory:
            # Set the path
            self.txtOutputDir.setText(directory)
            self.check_paths()
            self.store_paths_to_config()
            self.log('Changed the output directory to ' + directory)

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
