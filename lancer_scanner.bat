@echo off
set PATH=%PATH%;C:\Users\julie\miniconda3\Scripts;C:\Users\julie\miniconda3\condabin
cd /d "%~dp0"
echo 🚀 Activation de l'environnement simcomp...
call conda activate simcomp
echo 📊 Lancement du Market Scanner...
streamlit run streamlit_app.py
pause