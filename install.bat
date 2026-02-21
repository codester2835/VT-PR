@echo off
setlocal

rem Resolve the path to your local Python 3.12
rem You may need this if you have 3.14 installed to path
set PYTHON=%~dp0..\python 312\python.exe

echo Using Python at: %PYTHON%

rem Install Poetry
"%PYTHON%" -m pip install poetry==1.8.5

rem Configure Poetry to put virtualenvs inside the project
"%PYTHON%" -m poetry config virtualenvs.in-project true

rem Lock dependencies without updating
"%PYTHON%" -m poetry lock --no-update

rem Install dependencies
"%PYTHON%" -m poetry install

endlocal