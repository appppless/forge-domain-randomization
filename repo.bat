@echo off
setlocal
set "ISAAC_DEV=C:\isaac-sim-standalone-6.0.0-windows-x86_64\kit\dev"
set "REPO_ROOT=%~dp0"
set "REPO_ROOT=%REPO_ROOT:~0,-1%"
if not defined PM_PACKAGES_ROOT set "PM_PACKAGES_ROOT=D:\packman-repo"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"
set "PYTHONPATH=%ISAAC_DEV%\_repo\deps\repo_man;%ISAAC_DEV%\_repo\deps\repo_build;%ISAAC_DEV%\_repo\deps\repo_test;%ISAAC_DEV%\_repo\deps\repo_ci;%ISAAC_DEV%\_repo\deps\repo_format;%ISAAC_DEV%\_repo\deps\repo_package;%ISAAC_DEV%\_repo\deps\repo_source;%ISAAC_DEV%\_repo\deps\repo_kit_tools;%ISAAC_DEV%\tools\repoman;%PYTHONPATH%"
call "%ISAAC_DEV%\tools\packman\python.bat" -c "import omni.repo.man; omni.repo.man.main(r'%REPO_ROOT%')" %*
exit /b %ERRORLEVEL%
