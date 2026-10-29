"""바탕화면/시작 메뉴 아이콘이 실행하는 런처: 서버를 띄우고 주소창 없는 앱 창(Edge 앱 모드)을 연다.

설치판(exe)에서는 이 파일이 exe 의 진입점이라, 실행 인자에 따라 다른 역할을 맡는다:
--server 앱 서버 / --mcp Claude 연동 서버 / --register-mcp, --unregister-mcp Claude 설정에 등록·해제."""
import ctypes
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE = Path(__file__).parent
URL = f"http://127.0.0.1:{int(os.environ.get('COLDMAIL_PORT', 8765))}"
LOCAL = Path(os.environ["LOCALAPPDATA"]) / "ColdMailSender"  # 가상환경, 서버 로그, 앱 창 프로필
FROZEN = getattr(sys, "frozen", False)


def alive():
    try:
        with urllib.request.urlopen(URL + "/api/ping", timeout=1):
            return True
    except OSError:
        return False


def ensure_server():
    if alive():
        return
    LOCAL.mkdir(parents=True, exist_ok=True)
    with open(LOCAL / "server.log", "a", encoding="utf-8") as log:
        # 런처가 끝나도 서버는 계속 살아 있도록 분리해서 띄운다 (창이 닫히고 3분 뒤 스스로 종료)
        cmd = [sys.executable, "--server"] if FROZEN else [sys.executable, str(BASE / "app.py")]
        subprocess.Popen(cmd, cwd=BASE,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(150):
        if alive():
            return
        time.sleep(0.1)
    raise RuntimeError(f"앱 서버를 시작하지 못했습니다. 로그를 확인하세요:\n{LOCAL / 'server.log'}")


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base and (p := Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe").exists():
            return p
    return None


def run_mode(mode):
    if mode == "--server":
        if sys.stderr is None:  # 창 없는 exe 는 출력 대상이 없을 수 있다
            LOCAL.mkdir(parents=True, exist_ok=True)
            sys.stdout = sys.stderr = open(LOCAL / "server.log", "a", encoding="utf-8")
        import app
        app.main()
    elif mode == "--mcp":
        import mcp_server
        mcp_server.mcp.run()
    elif mode in ("--register-mcp", "--unregister-mcp"):
        import claude_setup
        claude_setup.main(mode == "--register-mcp")


def main():
    if len(sys.argv) > 1:
        run_mode(sys.argv[1])
        return
    try:
        ensure_server()
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(None, str(e), "ColdMail Sender", 0x10)
        return
    edge = find_edge()
    if not edge:
        webbrowser.open(URL)
        return
    # 별도 프로필을 써서 평소 쓰는 Edge 창/탭과 섞이지 않게 한다
    subprocess.Popen([str(edge), f"--app={URL}", f"--user-data-dir={LOCAL / 'window'}",
                      "--window-size=1400,900", "--no-first-run", "--no-default-browser-check"])


main()
