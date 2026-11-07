@echo off
rem Récupère la base mise à jour par GitHub, puis régénère et ouvre le site local.
cd /d "%~dp0"
git pull
python generer_site.py --rendre
