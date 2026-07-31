@echo off
chcp 65001 >nul
rem 더블클릭하면 브라우저로 DesignMap 웹 화면이 열립니다. (윈도우용)
cd /d "%~dp0"

rem 파이썬 명령 찾기 (python 또는 py)
set "PY=python"
where python >nul 2>&1
if errorlevel 1 set "PY=py"

echo DesignMap 웹 화면을 준비 중입니다...

rem 웹 구성요소(streamlit, python-docx)가 없으면 자동 설치
%PY% -c "import streamlit, docx" >nul 2>&1
if errorlevel 1 (
    echo ^(처음 한 번^) 웹 화면 구성요소를 설치합니다...
    %PY% -m pip install -e .[web] >nul 2>&1
)

echo 브라우저가 곧 열립니다. 이 창은 닫지 마세요. ^(종료하려면 이 창에서 Ctrl+C 또는 창 닫기^)
%PY% -m streamlit run app.py

pause
