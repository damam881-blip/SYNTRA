@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [1/3] schema + model invariants
python tools\check_model.py
if errorlevel 1 goto fail

echo.
echo [2/3] configuration digest
python tools\configuration_digest.py --verify
if errorlevel 1 goto fail

echo.
echo [3/3] v1.0.1 limits and accepted-with-warning rules
python tools\test_limits.py
if errorlevel 1 goto fail

echo.
echo ALL CHECKS PASSED
exit /b 0

:fail
echo.
echo CHECKS FAILED
exit /b 1
