#!/bin/bash
# 더블클릭하면 최신 코드를 받아 적용합니다 (데이터는 그대로 유지).
cd "$(dirname "$0")" || exit 1

echo "==================================="
echo " DesignMap 업데이트"
echo "==================================="
echo ""
echo "[1/2] 최신 코드 받는 중..."
git pull

echo ""
echo "[2/2] 업데이트 적용 중..."
pip3 install -e . >/dev/null 2>&1 || python3 -m pip install -e . >/dev/null 2>&1

echo ""
echo "✅ 완료! 데이터(data 폴더)는 그대로 유지됩니다."
echo "이제 터미널에서 designmap 명령을 계속 쓰시면 됩니다."
echo ""
read -r -p "엔터 키를 누르면 창이 닫힙니다..."
