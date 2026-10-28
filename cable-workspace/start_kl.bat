@echo off
chcp 65001 >nul
cd /d "%~dp0"
set LOG=%~dp0start_kl.log
echo ==== %date% %time% ==== > "%LOG%"

set PY=py
py --version >nul 2>&1 || set PY=python
echo Python: %PY% >> "%LOG%"
%PY% --version >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Python не найден. Установите Python 3 с python.org и отметьте "Add to PATH".
  echo ОШИБКА: Python не найден >> "%LOG%"
  pause & exit /b 1
)

echo [1/3] Установка библиотек для расчёта по PDF...
%PY% -m pip install --disable-pip-version-check -r requirements-kl.txt >> "%LOG%" 2>&1
%PY% -c "import pdfplumber, openpyxl; print('libs ok')" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Не удалось установить pdfplumber/openpyxl. Подробности в start_kl.log
  pause & exit /b 1
)

echo [2/3] Остановка старого сервиса на порту 8765...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr LISTENING') do (
  echo kill PID %%a >> "%LOG%"
  taskkill /PID %%a /F >> "%LOG%" 2>&1
)
timeout /t 1 >nul

echo [3/3] Запуск сервиса: http://127.0.0.1:8765  (это окно не закрывайте)
echo starting server >> "%LOG%"
%PY% server.py 2>> "%LOG%"
echo Сервис остановлен. Подробности в start_kl.log
pause
