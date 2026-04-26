#!/bin/bash
echo "Mac용 AI 맛집 추천 앱 빌드를 시작합니다..."
pip3 install -r requirements.txt
pyinstaller --noconfirm --onedir --windowed --name "AI_Restaurant_Recommender" "app.py"
echo "빌드가 완료되었습니다! dist 폴더 안의 AI_Restaurant_Recommender.app을 확인해주세요."
