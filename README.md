# REAL Video Enhancer ビルド方法

このリポジトリは PySide6 製の GUI（リポジトリ直下・`src/`）と、推論バックエンド（`backend/`）で構成されています。
リリース用のパッケージング（PyInstaller 等）は含まれておらず、ソースから実行できる状態にすることが「ビルド」です。

## 必要なもの

- Git
- [uv](https://docs.astral.sh/uv/)（Python 3.12 系は uv が自動で用意します）
- FFmpeg（バックエンドの動画処理に使用）

## 1. 取得

```
git clone --recurse-submodules https://github.com/TNTwise/REAL-Video-Enhancer
cd REAL-Video-Enhancer
```

## 2. 仮想環境と GUI 依存パッケージ

```
uv venv --python 3.12
uv pip install -r requirements.txt
```

以降は `uv run` が `.venv` を使うため、仮想環境の有効化は不要です。

## 3. Qt コードの生成

GUI は Qt Designer のファイルとリソースから Python コードを生成して使います。リポジトリ直下で実行してください。

```
uv run pyside6-uic testRVEInterface.ui -o mainwindow.py
uv run pyside6-rcc resources.qrc -o resources_rc.py
```

`mainwindow.py` と `resources_rc.py` は生成物です。`.ui` や `.qrc`（アイコン）を変更したら再生成してください。

## 4. 実行（動作確認）

```
uv run REAL-Video-Enhancer.py
```

初回起動時に、アプリがバックエンド用の Python・FFmpeg などの依存関係を `CWD`（アプリのデータディレクトリ）へダウンロードします。

## 5. 単体実行ファイルの生成（PyInstaller）

手順 3 の生成物（`mainwindow.py`、`resources_rc.py`）がある状態で、リポジトリ直下で実行します。

```
uv pip install pyinstaller==6.16.0
uv run pyinstaller REAL-Video-Enhancer.py --onefile --noconfirm --noupx --noconsole --icon=icons/logo-v2.ico --distpath dist
```

- Windows では `dist\REAL-Video-Enhancer.exe`、Linux / macOS では `dist/REAL-Video-Enhancer` が 1 ファイルで生成されます。
- バックエンド（`backend/`）は実行ファイルに含まれません。実行ファイルと同じ場所に `backend` フォルダを配置し、そのフォルダをカレントディレクトリとして起動してください（`backend` がカレントディレクトリにある場合、アプリはそこをデータディレクトリとして使います）。

```
# Windows (PowerShell)
Copy-Item -Recurse backend dist\backend
cd dist
.\REAL-Video-Enhancer.exe

# Linux / macOS
cp -r backend dist/backend
cd dist
./REAL-Video-Enhancer
```

- Windows では PyInstaller 製の実行ファイルがウイルス対策ソフトに誤検知されることがあります。
- Linux では、旧ビルドは `libxcb-cursor` を `_internal/PySide6/Qt/lib/` に同梱していました。`--onefile` では同梱していないため、実行環境に `libxcb-cursor0` 等をインストールしてください。

## 6. バックエンド単体のセットアップ（任意）

バックエンドを直接動かす場合は、別の仮想環境で依存パッケージを入れます（CUDA 12.6 / PyTorch 2.7.0 前提）。

```
cd backend
uv venv --python 3.12
uv pip install --prerelease=allow -r requirements.txt --extra-index-url https://download.pytorch.org/whl/test/cu126
uv run rve-backend.py --version
```

## 7. テスト

リポジトリ直下で実行します。

```
uv run python -m unittest discover tests
```

- `tests/test_real_backend.py` は CPU 版 PyTorch が入っている場合のみ実行されます。
- GUI テストは `QT_QPA_PLATFORM=offscreen` で動作し、`pyside6-uic` を内部で呼び出します。
