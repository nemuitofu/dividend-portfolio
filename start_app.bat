@echo off
chcp 65001 > nul
title 高配当株ポートフォリオ管理アプリ

echo 高配当株ポートフォリオ管理アプリを起動しています...
echo ブラウザが自動的に開きます。しばらくお待ちください。
echo.
echo 終了するには、このウィンドウを閉じてください。
echo -----------------------------------------------

wsl -e bash -c "cd ~/sandbox_toromaru/dividend-portfolio && python -m streamlit run app.py"

echo.
echo アプリが終了しました。
pause
