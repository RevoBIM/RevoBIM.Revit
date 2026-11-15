@echo off
REM RevoBIM Arcade - the desktop build, outside Revit.
REM Finds a Python and hands over. Nothing in here touches Revit.

setlocal
set "HERE=%~dp0"

REM pythonw first, so no console window sits behind the game.
where pythonw.exe >nul 2>&1 && (
    start "" pythonw.exe "%HERE%RevoBIM Arcade.pyw" %*
    exit /b 0
)
where py.exe >nul 2>&1 && (
    start "" py.exe -3 -w "%HERE%RevoBIM Arcade.pyw" %*
    exit /b 0
)
where python.exe >nul 2>&1 && (
    start "" python.exe "%HERE%RevoBIM Arcade.pyw" %*
    exit /b 0
)

echo.
echo   RevoBIM Arcade needs Python 3 on this machine.
echo.
echo   It is not installed, or it is not on PATH.
echo   Get it from python.org - the standard installer includes
echo   tkinter, which is all this needs. Tick "Add to PATH".
echo.
echo   Nothing else is required: no pip, no packages.
echo.
pause
exit /b 1
