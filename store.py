"""데이터 저장: 설정(JSON), 비밀번호(Windows 자격 증명 관리자), 템플릿/리스트/첨부(파일),
엑셀·CSV·구글시트 가져오기, 발송 대기(JSON), 발송 기록(SQLite).
데이터 폴더는 기본 ./data(설치판은 %LOCALAPPDATA%\\ColdMailSender\\data), 환경변수 COLDMAIL_DATA 로 바꿀 수 있다(테스트용)."""
import csv
import io
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

import keyring
import openpyxl

BASE = Path(__file__).parent
# 설치판(exe)은 프로그램 폴더가 업데이트 때 덮어써지므로 데이터를 사용자 폴더에 둔다
DATA = Path(os.environ.get("COLDMAIL_DATA") or (Path(os.environ["LOCALAPPDATA"]) / "ColdMailSender" / "data"
                                               if getattr(sys, "frozen", False) else BASE / "data"))
TEMPLATES = DATA / "templates"
LISTS = DATA / "lists"
ATTACHMENTS = DATA / "attachments"
SETTINGS_FILE = DATA / "settings.json"
QUEUE_FILE = DATA / "queue.json"
LOG_DB = DATA / "sendlog.db"
for d in (TEMPLATES, LISTS, ATTACHMENTS):
    d.mkdir(parents=True, exist_ok=True)

KEYRING_SERVICE = "ColdMailSender"
TEMPLATE_EXTS = (".md", ".docx")

DEFAULT_SETTINGS = {
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_security": "starttls",  # "starttls"(587) 또는 "ssl"(465)
    "username": "",
    "from_name": "",
    "from_email": "",
    "imap_enabled": False,
    "imap_host": "",
    "imap_port": 993,
    "imap_sent_folder": "Sent",
    "base_delay_min": 5,  # 모든 메일 사이
    "base_delay_max": 20,
    "delay_min": 30,  # Google·Microsoft 가 받는 메일끼리 (같은 회사로 가는 메일 사이)
    "delay_max": 90,
}


# ---------- 설정 / 비밀번호 ----------

def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        s.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
    return s


def save_settings(new):
    s = load_settings()
    for key, default in DEFAULT_SETTINGS.items():
        if key not in new:
            continue
        v = new[key]
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int):
            try:
                v = int(v or 0)
            except (TypeError, ValueError):
                raise ValueError(f"'{key}' 값은 숫자여야 합니다")
        else:
            v = str(v).strip()
        s[key] = v
    if s["smtp_security"] not in ("starttls", "ssl"):
        raise ValueError("보안 방식은 STARTTLS 또는 SSL 이어야 합니다")
    for prefix in ("base_delay", "delay"):
        if s[prefix + "_min"] < 0 or s[prefix + "_max"] < s[prefix + "_min"]:
            raise ValueError("발송 간격: 최소 ≥ 0, 최대 ≥ 최소 여야 합니다")
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
    return s


def get_password(username):
    return keyring.get_password(KEYRING_SERVICE, username) if username else None


def set_password(username, password):
    if not username:
        raise ValueError("계정(아이디)을 먼저 입력하세요")
    keyring.set_password(KEYRING_SERVICE, username, password)


# ---------- 파일 이름 ----------

def _path(folder, name, must_exist=True, exts=None):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", str(name)).strip().lstrip(".")
    if not name:
        raise ValueError("이름이 비어 있습니다")
    if exts and Path(name).suffix.lower() not in exts:
        raise ValueError(f"{', '.join(exts)} 파일만 가능합니다")
    p = folder / name
    if must_exist and not p.exists():
        raise ValueError(f"찾을 수 없습니다: {name}")
    return p


# ---------- 템플릿 ----------

def list_templates():
    return sorted(p.name for p in TEMPLATES.iterdir()
                  if p.suffix.lower() in TEMPLATE_EXTS and not p.name.startswith("~$"))


def template_path(name, must_exist=True):
    return _path(TEMPLATES, name, must_exist, TEMPLATE_EXTS)


# ---------- 첨부파일 ----------

def list_attachments():
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(ATTACHMENTS.iterdir()) if p.is_file()]


def attachment_path(name, must_exist=True):
    return _path(ATTACHMENTS, name, must_exist)


def attachment_paths(names):
    paths = [attachment_path(n) for n in names]
    if sum(p.stat().st_size for p in paths) > 20 * 1024 * 1024:
        raise ValueError("첨부파일 합계가 20MB를 넘습니다 (대부분의 메일 서버 한도 초과)")
    return paths


# ---------- 수신자 리스트 ----------

EMAIL_COLUMN_NAMES = {"이메일", "email", "e-mail", "메일", "mail", "이메일주소", "메일주소"}


def list_lists():
    return sorted(p.stem for p in LISTS.glob("*.json"))


def _list_file(name, must_exist=True):
    p = _path(LISTS, name, must_exist=False)
    p = p.with_name(p.name + ".json")
    if must_exist and not p.exists():
        raise ValueError(f"리스트를 찾을 수 없습니다: {name}")
    return p


def load_list(name):
    return json.loads(_list_file(name).read_text("utf-8"))


def save_list(name, data):
    columns = [str(c).strip() for c in data.get("columns", [])]
    if any(not c for c in columns):
        raise ValueError("빈 열 이름이 있습니다")
    if len(set(columns)) != len(columns):
        raise ValueError("중복된 열 이름이 있습니다")
    rows = [[str(v if v is not None else "").strip() for v in (list(r) + [""] * len(columns))[:len(columns)]]
            for r in data.get("rows", [])]
    out = {"columns": columns, "rows": rows}
    if data.get("source"):  # 구글시트에서 가져온 리스트는 원본 주소를 기억해 다시 불러올 수 있게 한다
        out["source"] = data["source"]
    p = _list_file(name, must_exist=False)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    return p.stem


def delete_list(name):
    _list_file(name).unlink()


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d") if v.time() == datetime.min.time() else v.strftime("%Y-%m-%d %H:%M")
    return str(v).strip()


def read_table(filename, raw):
    """엑셀(.xlsx) 또는 CSV를 {columns, rows} 로 읽는다. 첫 줄은 열 이름."""
    ext = Path(filename).suffix.lower()
    if ext == ".xlsx":
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        grid = [[_cell(v) for v in row] for row in wb.worksheets[0].iter_rows(values_only=True)]
    elif ext == ".csv":
        for enc in ("utf-8-sig", "cp949"):  # 한글 엑셀에서 저장한 CSV는 대개 cp949
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("CSV 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949)")
        grid = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    else:
        raise ValueError(".xlsx 또는 .csv 파일만 가져올 수 있습니다")

    grid = [r for r in grid if any(r)]
    if not grid:
        raise ValueError("빈 파일입니다")
    header = grid[0]
    width = max((i + 1 for i, c in enumerate(header) if c), default=0)
    if not width:
        raise ValueError("첫 줄에 열 이름이 필요합니다")
    columns = [c or f"열{i + 1}" for i, c in enumerate(header[:width])]
    rows = [(r + [""] * width)[:width] for r in grid[1:]]
    return {"columns": columns, "rows": rows}


GSHEET_ID = re.compile(r"docs\.google\.com/spreadsheets/d/([\w-]+)")
GSHEET_NOT_SHARED = "시트를 열 수 없습니다. 구글시트 공유 설정을 '링크가 있는 모든 사용자 - 뷰어'로 바꿔주세요"


def fetch_google_sheet(url):
    """'링크가 있는 모든 사용자' 로 공유된 구글시트의 탭 하나(주소의 gid)를 CSV 로 받아 읽는다."""
    m = GSHEET_ID.search(url or "")
    if not m:
        raise ValueError("구글시트 주소가 아닙니다 (https://docs.google.com/spreadsheets/d/... 형식)")
    gid = re.search(r"[#&?]gid=(\d+)", url)
    export = f"https://docs.google.com/spreadsheets/d/{m[1]}/export?format=csv" + (f"&gid={gid[1]}" if gid else "")
    try:
        with urllib.request.urlopen(export, timeout=20) as r:
            ctype, raw = r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403, 404):
            raise ValueError(GSHEET_NOT_SHARED)
        raise
    if "text/csv" not in ctype:  # 비공개 시트는 로그인 페이지(HTML)로 넘어간다
        raise ValueError(GSHEET_NOT_SHARED)
    return read_table("sheet.csv", raw)


SAMPLES = BASE / "samples"
SAMPLE_LIST_FILE = "수신자리스트_샘플.xlsx"
SEEDED_MARKER = DATA / ".samples_added"


def seed_samples():
    """처음 실행할 때 한 번만 샘플 템플릿과 수신자 리스트를 넣는다 (지워도 다시 생기지 않음)."""
    if SEEDED_MARKER.exists():
        return
    if not list_templates() and not list_lists():
        for p in SAMPLES.iterdir():
            if p.suffix.lower() in TEMPLATE_EXTS:
                (TEMPLATES / p.name).write_bytes(p.read_bytes())
        save_list("샘플_수신자", read_table(SAMPLE_LIST_FILE, (SAMPLES / SAMPLE_LIST_FILE).read_bytes()))
    SEEDED_MARKER.write_text(datetime.now().isoformat(), "utf-8")


def find_email_column(columns, rows):
    for i, c in enumerate(columns):
        if c.strip().lower().replace(" ", "") in EMAIL_COLUMN_NAMES:
            return i
    for i in range(len(columns)):  # 열 이름이 다르면 값 대부분에 @ 가 있는 열
        vals = [r[i] for r in rows if r[i]]
        if vals and sum("@" in v for v in vals) / len(vals) > 0.8:
            return i
    return None


# ---------- 발송 대기 (Claude 등이 준비하고, 사람이 앱에서 확인 후 발송) ----------

def load_queue():
    return json.loads(QUEUE_FILE.read_text("utf-8")) if QUEUE_FILE.exists() else []


def _save_queue(items):
    QUEUE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")


def add_queue(item):
    item = {"id": uuid.uuid4().hex[:8], "created": datetime.now().strftime("%Y-%m-%d %H:%M"), **item}
    _save_queue(load_queue() + [item])
    return item


def remove_queue(item_id):
    _save_queue([i for i in load_queue() if i["id"] != item_id])


# ---------- 발송 기록 ----------

def _db():
    con = sqlite3.connect(LOG_DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS sends(
        id INTEGER PRIMARY KEY, ts TEXT, email TEXT, label TEXT, list TEXT,
        template TEXT, subject TEXT, status TEXT, error TEXT)""")
    return con


def add_log(email, label, list_name, template, subject, status, error=""):
    with closing(_db()) as con, con:
        con.execute("INSERT INTO sends(ts,email,label,list,template,subject,status,error) VALUES(?,?,?,?,?,?,?,?)",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), email, label, list_name, template, subject,
                     status, error))


def get_log(limit=2000):
    with closing(_db()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM sends ORDER BY id DESC LIMIT ?", (limit,))]


def sent_emails():
    with closing(_db()) as con:
        return {r[0].lower() for r in con.execute("SELECT DISTINCT email FROM sends WHERE status='sent'")}
