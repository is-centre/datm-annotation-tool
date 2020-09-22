@echo off

REM Run me in Anaconda Prompt with the corresponding environment enabled!

echo Running pyuic5...
call pyuic5 ui\datmant.ui -o ui\datmant_ui.py
echo Done.