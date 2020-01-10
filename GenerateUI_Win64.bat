@echo off

SET pyuicpath="C:\Users\Alex\.conda\envs\datm-annotation-tool\Library\bin\pyuic5"

echo Running pyuic5...

%PYUICPATH% ui\datmant.ui -o ui\datmant_ui.py

echo Done.
pause