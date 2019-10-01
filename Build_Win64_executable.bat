@echo off

pyinstaller --add-data "res/A.ico;res/" --add-data "res/loading.png;res/" datmant.py

echo Done.