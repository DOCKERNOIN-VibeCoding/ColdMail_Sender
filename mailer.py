"""템플릿 변환·치환, 메일 생성, SMTP 발송, IMAP 보낸편지함 저장."""
import base64
import functools
import html
import imaplib
import mimetypes
import re
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import dns.resolver
import mammoth
import markdown

PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATA_URI_IMG = re.compile(r'src="data:(image/[\w.+-]+);base64,([^"]+)"')


# ---------- 템플릿 ----------

def template_to_html(path):
    if path.suffix.lower() == ".docx":
        with open(path, "rb") as f:
            return mammoth.convert_to_html(f).value
    return md_to_html(path.read_text("utf-8"))


def md_to_html(text):
    # "extra"의 attr_list 는 줄 끝의 {{이름}} 을 속성으로 오인하므로 필요한 확장만 사용
    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])


def wrap_html(body):
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
            '<div style="font-family:\'Malgun Gothic\',\'Apple SD Gothic Neo\',sans-serif;'
            f'font-size:14px;line-height:1.7;color:#222">{body}</div></body></html>')


def placeholders(*texts):
    return sorted({m.strip() for t in texts for m in PLACEHOLDER.findall(t)})


# ---------- 조사 자동 교정: {{채널명}}가 → 쯔양이 / 안원잘부가 ----------
# (받침 있을 때, 받침 없을 때, 괄호 표기). 치환 필드 바로 뒤에 붙은 조사만 고친다.
JOSA_PAIRS = [
    ("이에요", "예요", "(이)에요"), ("이었", "였", "(이)었"), ("이랑", "랑", "(이)랑"),
    ("이나", "나", "(이)나"), ("이라", "라", "(이)라"), ("이며", "며", "(이)며"), ("이여", "여", "(이)여"),
    ("으로", "로", "(으)로"), ("은", "는", "(은)는"), ("이", "가", "(이)가"),
    ("을", "를", "(을)를"), ("과", "와", "(과)와"),
]
JOSA_FORMS = {}
for _pair in JOSA_PAIRS:
    _a, _b, _paren = _pair
    for _form in (f"{_a}/{_b}", f"{_b}/{_a}", _paren, _a, _b):
        JOSA_FORMS.setdefault(_form, _pair)
# 치환 필드 + (굵게 등 닫는 태그) + 조사
PLACEHOLDER_JOSA = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}((?:</[a-zA-Z0-9]+>)*)("
                              + "|".join(re.escape(f) for f in sorted(JOSA_FORMS, key=len, reverse=True)) + ")?")
DIGIT_FINAL = {"0": "other", "1": "ㄹ", "3": "other", "6": "other", "7": "ㄹ", "8": "ㄹ"}  # 영 일 삼 육 칠 팔
LETTER_FINAL = {"l": "ㄹ", "r": "ㄹ", "m": "other", "n": "other"}  # 엘 알 엠 엔 (나머지 알파벳은 받침 없음)


def final_consonant(word):
    """마지막 글자의 받침: None(없음), 'ㄹ', 'other'. 괄호·공백·이모지 등은 건너뛴다."""
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            jong = (ord(ch) - 0xAC00) % 28
            return None if jong == 0 else ("ㄹ" if jong == 8 else "other")
        if ch.isascii() and ch.isdigit():
            return DIGIT_FINAL.get(ch)
        if ch.isascii() and ch.isalpha():
            return LETTER_FINAL.get(ch.lower())
    return None


def choose_josa(form, word):
    with_final, without_final, _ = JOSA_FORMS[form]
    fc = final_consonant(word)
    if with_final == "으로":  # ㄹ 받침 뒤에는 '로' (서울로)
        return without_final if fc in (None, "ㄹ") else with_final
    return with_final if fc else without_final


# ---------- 겹치는 이름 합치기: {{채널명}} {{이름}} 님 → 고재영 님 (고재영 고재영 님 X) ----------
# 공백(과 서식 태그)만 사이에 둔 두 치환 필드의 값이 사실상 같으면 짧은 쪽(보통 이름)만 남긴다.
ADJACENT = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}((?:\s|&nbsp;|</?[a-zA-Z][^>]*>)+?)\{\{\s*([^{}]+?)\s*\}\}")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def _norm(v):
    return re.sub(r"[\W_]+", "", v.lower())


def same_name(a, b):
    """값이 같거나, 긴 쪽이 짧은 쪽 앞/뒤에 2글자 이하(TV, 채널, 공식 등)만 붙은 경우."""
    short, long_ = sorted((_norm(a), _norm(b)), key=len)
    return bool(short) and (long_.startswith(short) or long_.endswith(short)) and len(long_) - len(short) <= 2


def merge_same_names(text, row):
    pos = 0
    while m := ADJACENT.search(text, pos):
        va, vb = (str(row.get(m.group(k).strip(), "") or "") for k in (1, 3))
        if not same_name(va, vb):
            pos = m.end(2)  # 다음 쌍(두 번째 필드부터) 확인
            continue
        tags = "".join(TAG.findall(m.group(2)))  # 공백은 지우고 서식 태그는 유지
        keep = f"{tags}{{{{{m.group(3)}}}}}" if len(_norm(vb)) <= len(_norm(va)) else f"{{{{{m.group(1)}}}}}{tags}"
        text = text[:m.start()] + keep + text[m.end():]
        pos = m.start()  # 세 개 이상 이어진 경우를 위해 같은 자리부터 다시
    return text


# ---------- 선택 항목: '맞춤문단'으로 시작하는 열은 비어 있어도 되고, 비면 그 문단을 지운다 ----------
OPTIONAL_PREFIX = "맞춤문단"
# 한 문단(<p>)에 그 치환 필드 하나만 있는 경우 (굵게 등 서식 태그는 허용)
LONE_PARAGRAPH = re.compile(r"<p\b[^>]*>(?:\s|<(?!/?p\b)[^>]+>)*\{\{\s*([^{}]+?)\s*\}\}(?:\s|<(?!/?p\b)[^>]+>)*</p>\s*")


def is_optional(name):
    return name.replace(" ", "").startswith(OPTIONAL_PREFIX)


def drop_empty_optional(html_text, row):
    def rep(m):
        name = m.group(1).strip()
        return "" if is_optional(name) and not str(row.get(name, "") or "").strip() else m.group(0)
    return LONE_PARAGRAPH.sub(rep, html_text)


def fill(text, row, escape):
    """escape=True: HTML 본문 — 값 안의 줄바꿈은 <br> (빈 줄은 문단 간격), 빈 맞춤문단은 문단째 삭제.
    escape=False: 제목 — 메일 헤더에는 줄바꿈을 넣을 수 없으므로 공백으로."""
    if escape:
        text = drop_empty_optional(text, row)
    text = merge_same_names(text, row)

    def rep(m):
        raw = str(row.get(m.group(1).strip(), "") or "").replace("\r\n", "\n")
        josa = choose_josa(m.group(3), raw) if m.group(3) else ""
        value = html.escape(raw).replace("\n", "<br>") if escape else " ".join(raw.split())
        return value + m.group(2) + josa
    return PLACEHOLDER_JOSA.sub(rep, text)


def valid_email(email):
    return bool(EMAIL_RE.match(email))


# 받는 메일 서버(MX)가 이 이름으로 끝나면 그 회사가 받는다. 회사 도메인이라도 Workspace/365 를 쓰면 여기 걸린다.
BIG_PROVIDERS = {"google": ("google.com", "googlemail.com"), "microsoft": ("outlook.com",)}


@functools.cache
def mail_provider(domain):
    """'google' / 'microsoft' / None(그 밖). 조회에 실패하면 알 수 없으니 'unknown'(큰 곳처럼 긴 간격)."""
    try:
        hosts = [str(r.exchange).rstrip(".").lower() for r in dns.resolver.resolve(domain, "MX", lifetime=5)]
    except Exception:
        return "unknown"
    for name, suffixes in BIG_PROVIDERS.items():
        if any(h == s or h.endswith("." + s) for h in hosts for s in suffixes):
            return name
    return None


def html_to_text(h):
    """text/plain 대체 본문 (HTML만 있는 메일은 스팸 점수가 올라감)."""
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
               lambda m: m.group(2) if m.group(1) in m.group(2) else f"{m.group(2)} ({m.group(1)})", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|h[1-6]|tr|table|ul|ol)>", "\n\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "- ", h)
    h = re.sub(r"(?i)</li>", "\n", h)
    h = html.unescape(re.sub(r"<[^>]+>", "", h))
    h = re.sub(r"[ \t]+\n", "\n", h)
    return re.sub(r"\n{3,}", "\n\n", h).strip()


# ---------- 메일 생성 ----------

def build_message(s, to_email, subject, body_html, attachments):
    msg = EmailMessage()
    msg["From"] = formataddr((s["from_name"], s["from_email"]))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=s["from_email"].rsplit("@", 1)[-1])

    # docx 안의 이미지(data: URI)는 Gmail 등에서 차단되므로 cid 인라인 이미지로 바꾼다
    images = []

    def to_cid(m):
        cid = make_msgid(domain="coldmail.local")[1:-1]
        images.append((cid, m.group(1), base64.b64decode(m.group(2))))
        return f'src="cid:{cid}"'

    body_html = DATA_URI_IMG.sub(to_cid, body_html)
    msg.set_content(html_to_text(body_html))
    msg.add_alternative(wrap_html(body_html), subtype="html")
    if images:
        html_part = msg.get_payload()[1]
        for cid, ctype, data in images:
            maintype, subtype = ctype.split("/", 1)
            html_part.add_related(data, maintype=maintype, subtype=subtype, cid=f"<{cid}>")

    for p in attachments:
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return msg


# ---------- SMTP / IMAP ----------

def smtp_connect(s, password):
    ctx = ssl.create_default_context()
    if s["smtp_security"] == "ssl":
        conn = smtplib.SMTP_SSL(s["smtp_host"], s["smtp_port"], timeout=30, context=ctx)
    else:
        conn = smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=30)
    try:
        if s["smtp_security"] == "starttls":
            conn.starttls(context=ctx)
        conn.login(s["username"], password)
    except Exception:
        conn.close()
        raise
    return conn


def send(s, password, msg):
    with smtp_connect(s, password) as conn:
        conn.send_message(msg)


def imap_connect(s, password):
    im = imaplib.IMAP4_SSL(s["imap_host"], s["imap_port"], timeout=30)
    try:
        im.login(s["username"], password)
    except Exception:
        im.shutdown()
        raise
    return im


LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\) (?P<delim>"[^"]*"|NIL) (?P<name>.+)')


def imap_folders(s, password):
    """폴더 목록과, 보낸편지함으로 추정되는 폴더를 돌려준다."""
    with imap_connect(s, password) as im:
        _, data = im.list()
    folders, guess = [], None
    for line in data:
        m = LIST_LINE.match(line) if isinstance(line, bytes) else None
        if not m:
            continue
        name = m["name"].decode("utf-8", "replace").strip()
        if len(name) >= 2 and name[0] == name[-1] == '"':
            name = name[1:-1].replace('\\"', '"')
        folders.append(name)
        if b"\\Sent" in m["flags"]:
            guess = name
    if not guess:
        guess = next((f for f in folders if f.lower() in ("sent", "sent items", "sent messages", "sent mail")), None)
    return folders, guess


def imap_save_sent(s, password, msg):
    folder = '"' + s["imap_sent_folder"].replace("\\", "\\\\").replace('"', '\\"') + '"'
    with imap_connect(s, password) as im:
        im.append(folder, "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())


def friendly_error(e):
    if isinstance(e, smtplib.SMTPAuthenticationError) or (
            isinstance(e, imaplib.IMAP4.error) and "auth" in str(e).lower()):
        return "로그인 실패: 아이디/비밀번호를 확인하세요. Gmail은 '앱 비밀번호'가 필요합니다."
    if isinstance(e, socket.gaierror):
        return "서버 주소를 찾을 수 없습니다. 호스트 이름을 확인하세요."
    if isinstance(e, (TimeoutError, ConnectionRefusedError)):
        return "서버에 연결할 수 없습니다. 주소/포트/보안 방식(SSL·STARTTLS)을 확인하세요."
    if isinstance(e, ssl.SSLError):
        return f"보안 연결 오류: 포트와 보안 방식 조합을 확인하세요 (465=SSL, 587=STARTTLS). ({e})"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "수신 주소가 거부되었습니다: " + "; ".join(
            f"{k}: {v[1].decode(errors='replace') if isinstance(v[1], bytes) else v[1]}" for k, v in e.recipients.items())
    if isinstance(e, smtplib.SMTPResponseException):
        err = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return f"SMTP 오류 {e.smtp_code}: {err}"
    return f"{type(e).__name__}: {e}"
