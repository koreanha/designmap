#!/bin/bash
# 더블클릭하면 브라우저로 DesignMap 웹 화면이 열립니다.
cd "$(dirname "$0")" || exit 1

echo "DesignMap 웹 화면을 준비 중입니다..."

# 웹 구성요소(streamlit, python-docx)가 없으면 자동 설치
if ! python3 -c "import streamlit, docx" >/dev/null 2>&1; then
    echo "(처음 한 번) 웹 화면 구성요소를 설치합니다..."
    pip3 install -e ".[web]" >/dev/null 2>&1 || python3 -m pip install streamlit python-docx >/dev/null 2>&1
fi

echo "브라우저가 곧 열립니다. (이 창은 닫지 마세요. 종료하려면 이 창에서 Control+C)"
python3 -m streamlit run app.py
