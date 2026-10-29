"""설치판: Claude 데스크톱·Claude Code 설정 파일에 이 exe 의 MCP 서버를 등록/해제한다.
설치 프로그램이 설치·제거 때 실행하고, 시작 메뉴 'ColdMail Sender Claude 연결'로 다시 실행할 수 있다."""
import ctypes
import json
import os
import sys
from pathlib import Path

NAME = "coldmail-sender"


def config_files():
    """설치되어 있는 Claude 의 설정 파일들. Microsoft Store 판 Claude 데스크톱은 설정이 패키지 폴더 안에 있다."""
    appdata, local = Path(os.environ["APPDATA"]), Path(os.environ["LOCALAPPDATA"])
    dirs = [appdata / "Claude", *(local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude")]
    found = [("Claude 데스크톱", d / "claude_desktop_config.json", False) for d in dirs if d.is_dir()]
    code = Path.home() / ".claude.json"
    if code.exists():
        found.append(("Claude Code", code, True))
    return found


def update(path, entry):
    """mcpServers 의 우리 항목만 바꾸고 나머지 설정은 그대로 둔다. entry=None 이면 삭제."""
    d = json.loads(path.read_text("utf-8")) if path.exists() else {}
    servers = d.setdefault("mcpServers", {})
    if entry is None:
        if servers.pop(NAME, None) is None:
            return
    else:
        servers[NAME] = entry
    tmp = path.with_name(path.name + ".coldmail.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def main(register):
    done, failed = [], []
    for label, path, is_code in config_files():
        entry = {"command": sys.executable, "args": ["--mcp"]}
        if is_code:
            entry = {"type": "stdio", **entry, "env": {}}
        try:
            update(path, entry if register else None)
            done.append(label)
        except Exception as e:  # 설정 파일이 깨져 있으면 건드리지 않는다
            failed.append(f"{label}: {e}")
    if not register:
        return
    if done:
        text = (f"Claude 연동을 설정했습니다: {', '.join(dict.fromkeys(done))}\n\n"
                "Claude 를 완전히 종료했다가(작업 표시줄 오른쪽 트레이 아이콘 → 종료) 다시 실행하세요.")
    else:
        text = ("Claude 데스크톱이나 Claude Code 를 찾지 못했습니다.\n"
                "Claude 를 설치한 뒤 시작 메뉴의 'ColdMail Sender Claude 연결'을 실행하세요.")
    if failed:
        text += "\n\n설정하지 못한 곳:\n" + "\n".join(failed)
    ctypes.windll.user32.MessageBoxW(None, text, "ColdMail Sender", 0x40)
