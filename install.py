"""setup.bat 이 실행: 바탕화면/시작 메뉴 바로가기를 만들고 Claude 연동 방법을 안내한다."""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent.resolve()
PYTHON = Path(sys.executable)


def ps_quote(p):
    return str(p).replace("'", "''")


def make_shortcuts():
    script = f"""
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
  $s = $ws.CreateShortcut((Join-Path $dir 'ColdMail Sender.lnk'))
  $s.TargetPath = '{ps_quote(PYTHON.with_name("pythonw.exe"))}'
  $s.Arguments = '"{ps_quote(BASE / "launcher.pyw")}"'
  $s.WorkingDirectory = '{ps_quote(BASE)}'
  $s.IconLocation = '{ps_quote(BASE / "static" / "app.ico")}'
  $s.Description = 'ColdMail Sender'
  $s.Save()
}}"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=True)


def main():
    make_shortcuts()
    mcp = {"command": str(PYTHON), "args": [str(BASE / "mcp_server.py")]}
    print("\n바로가기를 만들었습니다: 바탕화면과 시작 메뉴의 'ColdMail Sender'\n")
    print("[Claude Code 연동] 아래 명령을 한 번 실행하세요:")
    print(f'  claude mcp add coldmail-sender --scope user -- "{mcp["command"]}" "{mcp["args"][0]}"\n')
    print("[Claude 데스크톱 / Cowork 연동] 설정 > 개발자 > 구성 편집 에서 mcpServers 에 추가하세요:")
    print(json.dumps({"mcpServers": {"coldmail-sender": mcp}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
