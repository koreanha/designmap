@echo off
chcp 65001 >nul
rem 더블클릭하면 최신 코드를 받아 적용합니다 (데이터는 그대로 유지). (윈도우용)
cd /d "%~dp0"

set "PY=python"
where python >nul 2>&1
if errorlevel 1 set "PY=py"

echo ===================================
echo  DesignMap 업데이트
echo ===================================
echo.
echo [1/2] 최신 코드 받는 중...
git pull

echo.
echo [2/2] 업데이트 적용 중...
%PY% -m pip install -e .[web] >nul 2>&1

echo.
echo 완료! 데이터(data 폴더)는 그대로 유지됩니다.
echo 이제 "웹화면_실행.bat"을 더블클릭해 사용하세요.
echo.
pause
