"""ColdMail Sender 로컬 서버. 보통은 launcher.pyw(바탕화면 아이콘)나 mcp_server.py 가 백그라운드로 띄운다."""
import logging
import os
import random
import threading
import time

from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

import mailer
import store

HOST, PORT = "127.0.0.1", int(os.environ.get("COLDMAIL_PORT", 8765))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MAX_CONSECUTIVE_FAILURES = 3
IDLE_EXIT_SECONDS = 180  # 앱 창이 닫히고(하트비트 끊김) 발송도 없으면 서버를 끈다

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
LAST_REQUEST = time.time()


@app.before_request
def local_only():
    global LAST_REQUEST
    LAST_REQUEST = time.time()
    # 다른 웹사이트가 이 로컬 서버로 요청을 보내지 못하게 막는다 (CSRF / DNS 리바인딩)
    if request.host not in ALLOWED_HOSTS:
        abort(403)
    origin = request.headers.get("Origin")
    if origin and origin.split("://", 1)[-1] not in ALLOWED_HOSTS:
        abort(403)


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    if isinstance(e, ValueError):
        return jsonify(error=str(e)), 400
    app.logger.exception(e)
    return jsonify(error=f"{type(e).__name__}: {e}"), 500


def body():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValueError("잘못된 요청입니다")
    return d


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/ping")
def ping():
    return jsonify(ok=True)


# ---------- 설정 ----------

def settings_response():
    s = store.load_settings()
    return jsonify(s | {"has_password": bool(store.get_password(s["username"]))})


def credentials():
    s = store.load_settings()
    if not (s["smtp_host"] and s["username"] and s["from_email"]):
        raise ValueError("설정 탭에서 SMTP 서버, 계정, 보내는 주소를 먼저 저장하세요")
    pw = store.get_password(s["username"])
    if not pw:
        raise ValueError("비밀번호가 저장되어 있지 않습니다. 설정 탭에서 입력하세요")
    return s, pw


@app.get("/api/settings")
def get_settings():
    return settings_response()


@app.post("/api/settings")
def post_settings():
    d = body()
    s = store.save_settings(d)
    if d.get("password"):
        store.set_password(s["username"], d["password"])
    return settings_response()


@app.post("/api/settings/test")
def test_settings():
    s, pw = credentials()
    out = {}
    try:
        mailer.smtp_connect(s, pw).quit()
        out["smtp"] = "ok"
    except Exception as e:
        out["smtp"] = mailer.friendly_error(e)
    if s["imap_enabled"]:
        try:
            out["folders"], out["sent_guess"] = mailer.imap_folders(s, pw)
            out["imap"] = "ok"
        except Exception as e:
            out["imap"] = mailer.friendly_error(e)
    return jsonify(out)


# ---------- 템플릿 ----------

@app.get("/api/templates")
def templates():
    return jsonify(store.list_templates())


@app.get("/api/templates/<name>")
def get_template(name):
    p = store.template_path(name)
    is_md = p.suffix.lower() == ".md"
    return jsonify(name=p.name, kind="md" if is_md else "docx",
                   source=p.read_text("utf-8") if is_md else None,
                   html=mailer.wrap_html(mailer.template_to_html(p)))


@app.put("/api/templates/<name>")
def put_template(name):
    p = store.template_path(name, must_exist=False)
    if p.suffix.lower() != ".md":
        raise ValueError("앱에서는 .md 템플릿만 편집할 수 있습니다")
    p.write_text(body().get("source", ""), "utf-8")
    return jsonify(name=p.name)


@app.post("/api/templates/render")
def render_template_source():
    return jsonify(html=mailer.wrap_html(mailer.md_to_html(body().get("source", ""))))


@app.post("/api/templates/upload")
def upload_template():
    f = request.files.get("file")
    if not f:
        raise ValueError("파일이 없습니다")
    p = store.template_path(f.filename, must_exist=False)
    f.save(p)
    return jsonify(name=p.name)


@app.delete("/api/templates/<name>")
def delete_template(name):
    store.template_path(name).unlink()
    return jsonify(ok=True)


@app.post("/api/open-folder/<kind>")
def open_folder(kind):
    folders = {"templates": store.TEMPLATES, "attachments": store.ATTACHMENTS, "lists": store.LISTS}
    if kind not in folders:
        abort(404)
    os.startfile(folders[kind])
    return jsonify(ok=True)


# ---------- 수신자 리스트 ----------

@app.get("/api/lists")
def lists():
    return jsonify(store.list_lists())


@app.get("/api/lists/<name>")
def get_list(name):
    return jsonify(store.load_list(name))


@app.put("/api/lists/<name>")
def put_list(name):
    return jsonify(name=store.save_list(name, body()))


@app.post("/api/lists/import")
def import_list():
    f = request.files.get("file")
    name = (request.form.get("name") or "").strip()
    if not f or not name:
        raise ValueError("파일과 리스트 이름이 필요합니다")
    return jsonify(name=store.save_list(name, store.read_table(f.filename, f.read())))


@app.post("/api/lists/import-gsheet")
def import_gsheet():
    d = body()
    name, url = (d.get("name") or "").strip(), (d.get("url") or "").strip()
    if not name:
        raise ValueError("리스트 이름이 필요합니다")
    return jsonify(name=store.save_list(name, {**store.fetch_google_sheet(url), "source": url}))


@app.delete("/api/lists/<name>")
def delete_list(name):
    store.delete_list(name)
    return jsonify(ok=True)


@app.get("/api/sample-list.<ext>")
def sample_list(ext):
    if ext not in ("xlsx", "csv"):
        abort(404)
    return send_file(store.SAMPLES / f"수신자리스트_샘플.{ext}", as_attachment=True)


# ---------- 첨부파일 ----------

@app.get("/api/attachments")
def attachments():
    return jsonify(store.list_attachments())


@app.post("/api/attachments")
def upload_attachments():
    for f in request.files.getlist("files"):
        f.save(store.attachment_path(f.filename, must_exist=False))
    return jsonify(store.list_attachments())


@app.delete("/api/attachments/<name>")
def delete_attachment(name):
    store.attachment_path(name).unlink()
    return jsonify(store.list_attachments())


# ---------- 발송 준비 / 미리보기 ----------

def load_campaign(d):
    subject = (d.get("subject") or "").strip()
    if not subject:
        raise ValueError("메일 제목을 입력하세요")
    if not d.get("template") or not d.get("list"):
        raise ValueError("템플릿과 수신자 리스트를 선택하세요")
    html_src = mailer.template_to_html(store.template_path(d["template"]))
    data = store.load_list(d["list"])
    ecol = store.find_email_column(data["columns"], data["rows"])
    if ecol is None:
        raise ValueError("리스트에 '이메일' 열이 필요합니다")
    return subject, html_src, data["columns"], data["rows"], ecol


def row_dict(columns, row):
    return dict(zip(columns, row))


def row_label(columns, row, ecol):
    """기록/목록에 보여줄 수신자 이름: 이메일 외 앞쪽 두 열."""
    return " / ".join([v for i, v in enumerate(row) if i != ecol and v][:2])


def row_at(rows, idx):
    idx = int(idx)
    if not 0 <= idx < len(rows):
        raise ValueError("리스트가 변경되었습니다. '수신자 확인'을 다시 눌러주세요")
    return rows[idx]


@app.post("/api/prepare")
def prepare():
    subject, html_src, columns, rows, ecol = load_campaign(body())
    used = mailer.placeholders(subject, html_src)
    sent = store.sent_emails()
    seen, recipients = set(), []
    for i, row in enumerate(rows):
        if not any(row):
            continue
        rd = row_dict(columns, row)
        email = row[ecol].strip()
        key = email.lower()
        recipients.append({
            "idx": i, "email": email, "label": row_label(columns, row, ecol),
            "invalid": not mailer.valid_email(email),
            "duplicate": key in seen,
            "already_sent": key in sent,
            "missing": [p for p in used if p in rd and not rd[p] and not mailer.is_optional(p)],
            "omitted": [p for p in used if p in rd and not rd[p] and mailer.is_optional(p)],  # 빈 맞춤문단(생략)
        })
        seen.add(key)
    return jsonify(placeholders=used, unknown=[p for p in used if p not in columns], recipients=recipients)


@app.post("/api/render")
def render():
    d = body()
    subject, html_src, columns, rows, _ = load_campaign(d)
    rd = row_dict(columns, row_at(rows, d.get("idx", 0)))
    return jsonify(subject=mailer.fill(subject, rd, False), html=mailer.wrap_html(mailer.fill(html_src, rd, True)))


@app.post("/api/test-send")
def test_send():
    d = body()
    s, pw = credentials()
    subject, html_src, columns, rows, _ = load_campaign(d)
    rd = row_dict(columns, row_at(rows, d.get("idx", 0)))
    msg = mailer.build_message(s, s["from_email"], "[테스트] " + mailer.fill(subject, rd, False),
                               mailer.fill(html_src, rd, True), store.attachment_paths(d.get("attachments", [])))
    try:
        mailer.send(s, pw, msg)
    except Exception as e:
        raise ValueError(mailer.friendly_error(e))
    return jsonify(to=s["from_email"])


# ---------- 발송 작업 ----------

JOB = {"status": "idle"}
JOB_LOCK = threading.Lock()
STOP = threading.Event()


@app.post("/api/send")
def start_send():
    d = body()
    s, pw = credentials()
    subject, html_src, columns, rows, ecol = load_campaign(d)
    atts = store.attachment_paths(d.get("attachments", []))
    targets, seen = [], set()
    for idx in d.get("indices", []):
        row = row_at(rows, idx)
        email = row[ecol].strip()
        if mailer.valid_email(email) and email.lower() not in seen:
            seen.add(email.lower())
            targets.append((email, row_label(columns, row, ecol), row_dict(columns, row)))
    if not targets:
        raise ValueError("발송할 수신자가 없습니다")
    with JOB_LOCK:
        if JOB["status"] in ("running", "stopping"):
            raise ValueError("이미 발송이 진행 중입니다")
        STOP.clear()
        JOB.clear()
        JOB.update(status="running", total=len(targets), sent=0, failed=0, items=[], current=None, next_at=None,
                   message="")
    threading.Thread(target=run_job, daemon=True,
                     args=(s, pw, subject, html_src, atts, targets, d["template"], d["list"])).start()
    return job_status()


def run_job(s, pw, subject, html_src, atts, targets, template, list_name):
    consecutive_failures = 0
    with JOB_LOCK:
        JOB["message"] = "받는 메일 서버 확인 중…"
    # 받는 쪽 스팸 필터는 자기 서버로 들어온 메일끼리의 간격을 본다. 그래서 Google·Microsoft 로 가는 메일만
    # 같은 곳끼리 긴 간격을 두고, 그 사이에 다른 주소는 짧은 기본 간격으로 보낸다.
    pending = [(email, label, rd, mailer.mail_provider(email.rsplit("@", 1)[1].lower()))
               for email, label, rd in targets]
    with JOB_LOCK:
        JOB["message"] = ""
    group_ready = {}  # 그룹별 다음 발송 가능 시각
    next_any = time.time()
    while pending and not STOP.is_set():
        # 리스트 순서대로 보내되, 간격을 기다려야 하는 메일보다 지금 보낼 수 있는 메일이 있으면 그것부터
        i = min(range(len(pending)), key=lambda i: (max(group_ready.get(pending[i][3], 0), next_any), i))
        email, label, rd, group = pending.pop(i)
        at = max(next_any, group_ready.get(group, 0))
        if at > time.time():
            with JOB_LOCK:
                JOB["next_at"] = at
            if STOP.wait(at - time.time()):
                break
        with JOB_LOCK:
            JOB.update(current=email, next_at=None)
        subj = mailer.fill(subject, rd, False)
        error = warning = ""
        try:
            msg = mailer.build_message(s, email, subj, mailer.fill(html_src, rd, True), atts)
            mailer.send(s, pw, msg)
            if s["imap_enabled"]:
                try:
                    mailer.imap_save_sent(s, pw, msg)
                except Exception as e:
                    warning = "보낸편지함 저장 실패: " + mailer.friendly_error(e)
        except Exception as e:
            error = mailer.friendly_error(e)
        store.add_log(email, label, list_name, template, subj, "failed" if error else "sent", error or warning)
        consecutive_failures = consecutive_failures + 1 if error else 0
        with JOB_LOCK:
            JOB["failed" if error else "sent"] += 1
            JOB["items"].insert(0, {"email": email, "label": label, "ok": not error, "note": error or warning})
            JOB["current"] = None
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            with JOB_LOCK:
                JOB.update(status="aborted", message=f"{MAX_CONSECUTIVE_FAILURES}회 연속 실패로 중단했습니다. "
                                                     "계정 상태와 설정을 확인하세요.")
            return
        # 일정 간격 기계적 발송을 피하려고 매번 무작위로 정한다
        now = time.time()
        next_any = now + random.uniform(s["base_delay_min"], s["base_delay_max"])
        if group:
            group_ready[group] = now + random.uniform(s["delay_min"], s["delay_max"])
    with JOB_LOCK:
        JOB.update(status="stopped" if STOP.is_set() else "done", current=None, next_at=None)


@app.get("/api/job")
def job_status():
    with JOB_LOCK:
        return jsonify(JOB | {"items": list(JOB.get("items", []))})


@app.post("/api/job/stop")
def stop_job():
    STOP.set()
    with JOB_LOCK:
        if JOB["status"] == "running":
            JOB["status"] = "stopping"
    return job_status()


@app.get("/api/log")
def log():
    return jsonify(store.get_log())


# ---------- 발송 대기 ----------

@app.get("/api/queue")
def queue():
    return jsonify(store.load_queue())


@app.post("/api/queue")
def add_queue():
    d = body()
    _, _, _, rows, _ = load_campaign(d)
    attachments = d.get("attachments") or []
    store.attachment_paths(attachments)
    indices = d.get("indices")
    if indices is not None:
        indices = [int(i) for i in indices]
        for i in indices:
            row_at(rows, i)
    return jsonify(store.add_queue({"template": d["template"], "list": d["list"], "subject": d["subject"].strip(),
                                    "attachments": attachments, "indices": indices, "note": d.get("note", "")}))


@app.delete("/api/queue/<item_id>")
def delete_queue(item_id):
    store.remove_queue(item_id)
    return jsonify(ok=True)


def exit_when_idle():
    while True:
        time.sleep(15)
        with JOB_LOCK:
            busy = JOB["status"] in ("running", "stopping")
        if not busy and time.time() - LAST_REQUEST > IDLE_EXIT_SECONDS:
            os._exit(0)


def main():
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # 요청마다 로그가 쌓이지 않게
    store.seed_samples()
    threading.Thread(target=exit_when_idle, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
