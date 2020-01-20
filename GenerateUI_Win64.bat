@echo off

REM SET pyuicpath="C:\Users\Alex\.conda\envs\datm-annotation-tool\Library\bin\pyuic5"
SET pyuicpath="C:\Anaconda\envs\datm-annotation-tool\Library\bin\pyuic5"

echo Running pyuic5...

%PYUICPATH% ui\datmant.ui -o ui\datmant_ui.py

echo Done.
pause