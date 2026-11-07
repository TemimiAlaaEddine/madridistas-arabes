@echo off
chcp 65001 >nul
rem Recupere la base mise a jour par GitHub, puis regenere et ouvre le site local.
cd /d "%~dp0"
git pull
python generer_site.py --rendre
pause
