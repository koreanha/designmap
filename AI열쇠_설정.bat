@echo off
chcp 65001 >nul
rem AI 열쇠(ANTHROPIC_API_KEY)를 윈도우에 영구 저장합니다.
echo ===================================
echo  AI 열쇠 설정 (Claude API Key)
echo ===================================
echo.
echo console.anthropic.com 에서 발급받은 열쇠를 붙여넣고 엔터를 누르세요.
echo (열쇠는 sk-ant- 로 시작합니다. 붙여넣기: 마우스 오른쪽 클릭)
echo.
set /p KEY="AI 열쇠 입력: "

if "%KEY%"=="" (
    echo 입력이 비어 있어 취소했습니다.
    pause
    exit /b 1
)

setx ANTHROPIC_API_KEY "%KEY%" >nul
echo.
echo 저장 완료! 열려 있는 창은 인식하지 못하니,
echo "웹화면_실행.bat"을 **새로** 더블클릭해서 사용하세요.
echo.
pause
