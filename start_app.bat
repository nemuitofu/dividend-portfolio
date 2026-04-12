@echo off
chcp 65001 > nul
title 高配当株ポートフォリオ管理アプリ

echo 高配当株ポートフォリオ管理アプリを起動しています...
echo 終了するには、このウィンドウを閉じてください。
echo -----------------------------------------------

wsl -e bash -c "cd ~/sandbox_toromaru/dividend-portfolio && if [ ! -d .venv ]; then echo '初回セットアップ: 仮想環境を作成しています...' && python3 -m venv .venv && echo 'パッケージをインストールしています...' && .venv/bin/pip install -r requirements.txt; fi && .venv/bin/python -m streamlit run app.py"

echo.
echo アプリが終了しました。
pause
