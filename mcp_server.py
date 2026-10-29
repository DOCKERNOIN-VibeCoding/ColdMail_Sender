"""ColdMail Sender MCP 서버 - Claude Code / Claude 데스크톱(Cowork)에서 메일 준비 작업을 하게 해준다.

실제 대량 발송 도구는 일부러 없다. Claude 는 queue_campaign 으로 '발송 대기'에 올리고,
사람이 앱의 발송 탭에서 확인한 뒤 직접 발송한다. (테스트 발송은 내 주소로만 간다)

앱 서버를 띄우지 않고 app.py 의 API 를 이 프로세스 안에서 직접 호출한다(같은 데이터 파일 사용).
MCP 클라이언트는 세션이 끝나면 하위 프로세스를 모두 종료하므로, 여기서 서버를 띄우면
사용자가 그 서버로 진행 중인 발송까지 함께 끊길 수 있기 때문이다.
"""
import json
import urllib.parse
import urllib.request
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import app as webapp
import mailer

INSTRUCTIONS = """\
ColdMail Sender: 협업·영업 제안 메일을 수신자별로 내용을 바꿔 한 통씩 보내는 메일머지 앱.
(채널명/이름 대신 회사명/담당자명 등 어떤 열 이름이든 쓸 수 있다.)

## 핵심 개념
- 수신자 리스트 = 표. 열 이름은 자유, '이메일' 열은 필수. 한 행 = 한 수신자.
- 템플릿 = 마크다운 본문. {{열이름}} 자리에 그 행의 값이 들어간다. 제목도 {{열이름}} 을 쓸 수 있다.
- 수신자마다 내용을 다르게 쓰려면 '맞춤 내용은 리스트의 열로, 공통 부분은 템플릿으로' 나눈다. 별도 파일을 만들지 않는다.

## 수신자별로 다른 내용을 쓸 때 (권장 패턴)
1. 리스트에 맞춤 열을 둔다: '맞춤문단 1' ~ '맞춤문단 5'(본문 중 사람마다 다른 문단들), '제목'(사람마다 다른 제목).
   save_list(rows=[{"회사명": "...", "담당자명": "...", "이메일": "...", "제목": "...",
                    "맞춤문단 1": "...", "맞춤문단 2": "...", "맞춤문단 3": ""}, ...])
2. 템플릿은 공통 틀만 두고 맞춤 자리를 단독 문단으로 배치한다(각 {{맞춤문단 N}} 앞뒤를 빈 줄로 띄움). 권장 배치:
   인사말 / {{맞춤문단 1}} 연락 계기(최근 콘텐츠·사업 언급) / {{맞춤문단 2}} 제안 아이디어 / {{맞춤문단 3}} 기대 효과 /
   공통 소개·조건 / {{맞춤문단 4}} 조건·일정 관련 개별 메모 / {{맞춤문단 5}} 마무리 한마디 / 서명.
   overview 의 templates 에 '협업제안_맞춤형.md' 가 있으면 get_template 으로 형식을 참고하고, 없으면 위 배치대로 새로 만든다.
3. '맞춤문단'으로 시작하는 열은 선택 항목이다. 비어 있으면 그 문단이 통째로 빠지고 발송 대상에서도 제외되지 않는다.
   그러니 사람마다 필요한 개수만 채우면 된다(개수 제한 없음, 5개 권장). 번호 없는 '맞춤문단' 하나만 써도 된다.
   열 이름과 템플릿의 {{ }} 이름은 띄어쓰기까지 정확히 같아야 한다('맞춤문단 1' ≠ '맞춤문단1').
4. 통째로 다른 메일이면 템플릿을 '{{본문}}' + 서명 정도로 두고 본문 열에 전체를 쓴다.
5. 발송 제목은 '{{제목}}' 처럼 열을 그대로 넣으면 된다.
6. 메일 버전이 몇 개뿐이면 버전별 템플릿을 만들고 queue_campaign(row_numbers=...) 로 버전마다 따로 올려도 된다.

## 열 값(맞춤 문단 등) 작성 규칙
- 일반 텍스트로 쓴다. 줄바꿈(\\n)은 메일에서도 줄바꿈, 빈 줄(\\n\\n)은 문단 간격이 된다.
- 열 값 안의 마크다운(**굵게**, [링크](url))은 적용되지 않고 글자 그대로 보인다. 서식이 필요하면 템플릿 쪽에 둔다.
- 열 값 안의 조사는 자동 교정되지 않으므로 직접 맞게 쓴다.
- 제목 열에 줄바꿈을 넣으면 공백으로 바뀐다.

## 자동 처리 (템플릿 안의 {{열이름}} 바로 뒤)
- 한국어 조사 자동 교정: '{{채널명}}가' → 쯔양이 / 안원잘부가 (은/는, 이/가, 을/를, 과/와, 으로/로, 이랑/랑, 이나/나,
  이라/라, 이며/며, 이에요/예요, 이었/였, 이여/여). '이/가', '(이)가' 표기도 된다. 영어 값은 틀릴 수 있으니 preview 로 확인.
- 이름 합치기: 공백만 사이에 둔 두 필드 값이 사실상 같으면(같거나 TV·채널 등 2글자 이하 차이) 짧은 쪽만 남는다.
  '{{채널명}} {{이름}} 님' + 고재영TV/고재영 → '고재영 님'.

## 작업 순서
1. overview: 템플릿·리스트·첨부파일·보내는 계정·발송 대기 확인. account_ready 가 false 면 사용자에게 앱 설정 탭에서
   메일 계정을 먼저 설정하라고 안내한다.
2. send_history 로 이미 연락한 주소인지 확인한다.
3. save_list / import_google_sheet 로 리스트, save_template 으로 템플릿을 만든다.
4. preview 로 문제 행(주소 오류·중복·빈 값·발송 이력)을 확인하고, 맞춤 내용을 썼다면 row_numbers 로 모든 행의 실제 문안을 검토한다.
5. 필요하면 send_test 로 사용자 본인 주소에 테스트 메일을 보낸다.
6. queue_campaign 으로 '발송 대기'에 올리고, 사용자에게 앱(바탕화면 'ColdMail Sender')의 발송 탭 → 발송 대기 →
   불러오기 → 확인 후 발송 시작을 누르라고 안내한다. 이 도구들로는 대량 발송을 할 수 없다(의도된 설계).

row_number(s) 는 리스트의 1부터 시작하는 행 번호(앱 화면의 # 열)다.
"""

mcp = MCPServer("coldmail-sender", instructions=INSTRUCTIONS)


CLIENT = webapp.app.test_client()
BASE_URL = f"http://127.0.0.1:{webapp.PORT}"


def api(method, path, body=None):
    """앱 API 를 프로세스 안에서 호출. 오류는 ToolError 로 올려야 메시지가 Claude 에게 그대로 전달된다."""
    r = CLIENT.open(path, method=method, json=body, base_url=BASE_URL)
    data = r.get_json(silent=True)
    if r.status_code >= 400:
        raise ToolError((data or {}).get("error") or f"HTTP {r.status_code}")
    return data


def running_job():
    """진행 중인 발송은 사용자가 띄운 앱 서버에만 있다. 앱이 꺼져 있으면 None."""
    try:
        with urllib.request.urlopen(BASE_URL + "/api/job", timeout=1) as r:
            return json.loads(r.read())
    except OSError:
        return None


def q(name):
    return urllib.parse.quote(name, safe="")


def campaign(template, list_name, subject):
    return {"template": template, "list": list_name, "subject": subject}


@mcp.tool()
def overview() -> dict:
    """현재 상태: 템플릿/수신자 리스트/첨부파일 목록, 보내는 계정, 발송 대기 항목, 진행 중인 발송."""
    s = api("GET", "/api/settings")
    return {
        "templates": api("GET", "/api/templates"),
        "lists": api("GET", "/api/lists"),
        "attachments": [a["name"] for a in api("GET", "/api/attachments")],
        "sender": f'{s["from_name"]} <{s["from_email"]}>',
        "account_ready": bool(s["smtp_host"] and s["has_password"]),
        "queue": api("GET", "/api/queue"),
        "app_running": (job := running_job()) is not None,
        "job": job,
    }


@mcp.tool()
def get_template(name: str) -> dict:
    """템플릿 내용. .md 는 마크다운 원문, .docx 는 텍스트로 변환한 내용을 돌려준다."""
    t = api("GET", "/api/templates/" + q(name))
    return {"name": t["name"], "kind": t["kind"],
            "content": t["source"] if t["kind"] == "md" else mailer.html_to_text(t["html"])}


@mcp.tool()
def save_template(name: str, markdown: str) -> dict:
    """마크다운 템플릿을 만들거나 덮어쓴다. name 에 .md 가 없으면 붙인다. {{열이름}} 치환 필드 사용 가능."""
    if not name.lower().endswith(".md"):
        name += ".md"
    return api("PUT", "/api/templates/" + q(name), {"source": markdown})


@mcp.tool()
def get_list(name: str) -> dict:
    """수신자 리스트 내용. rows 는 {row_number, 열이름: 값} 객체 목록."""
    d = api("GET", "/api/lists/" + q(name))
    rows = [{"row_number": i + 1, **dict(zip(d["columns"], r))} for i, r in enumerate(d["rows"])]
    return {"name": name, "columns": d["columns"], "rows": rows, "google_sheet": d.get("source")}


@mcp.tool()
def save_list(name: str, rows: list[dict[str, Any]], mode: Literal["append", "replace"] = "append",
              columns: list[str] | None = None) -> dict:
    """수신자 리스트에 행을 추가(append)하거나 통째로 바꾼다(replace). 리스트가 없으면 새로 만든다.

    rows: [{"이름": "...", "채널명": "...", "이메일": "...", "맞춤문단": "여러 줄\\n가능"}, ...].
          처음 보는 열 이름은 새 열로 추가된다. 값의 줄바꿈은 메일에서도 유지된다(마크다운은 적용 안 됨).
    columns: 열 순서를 지정하고 싶을 때 (replace 에서 주로 사용). '이메일' 열은 필수.
    """
    existing = {"columns": [], "rows": []}
    if mode == "append" and name in api("GET", "/api/lists"):
        existing = api("GET", "/api/lists/" + q(name))
    cols = list(existing["columns"])
    for c in [*(columns or []), *(k for r in rows for k in r)]:
        if c != "row_number" and c not in cols:
            cols.append(c)
    old = [r + [""] * (len(cols) - len(r)) for r in existing["rows"]]
    new = [["" if r.get(c) is None else str(r.get(c)) for c in cols] for r in rows]
    api("PUT", "/api/lists/" + q(name), {"columns": cols, "rows": old + new, "source": existing.get("source")})
    return {"name": name, "columns": cols, "row_count": len(old) + len(new), "added": len(new)}


@mcp.tool()
def import_google_sheet(name: str, url: str) -> dict:
    """구글시트를 수신자 리스트로 가져온다(같은 이름이면 덮어씀). 시트는 '링크가 있는 모든 사용자 - 뷰어'로
    공유돼 있어야 한다. 비공개 시트라면 구글 드라이브 도구로 읽은 뒤 save_list(mode="replace")로 넣는다."""
    api("POST", "/api/lists/import-gsheet", {"name": name, "url": url})
    d = api("GET", "/api/lists/" + q(name))
    return {"name": name, "columns": d["columns"], "row_count": len(d["rows"])}


@mcp.tool()
def preview(template: str, list_name: str, subject: str, row_numbers: list[int] | None = None) -> dict:
    """발송 전 점검 + 실제 문안(치환·조사 교정·이름 합치기·빈 맞춤문단 생략이 적용된 제목과 본문).
    문제(주소 오류, 중복, 빈 치환 값, 이전 발송 이력)가 있는 행을 알려준다. 비어 있는 '맞춤문단…' 열은 문제가 아니라
    omitted_paragraphs 에 따로 나온다(그 문단을 빼고 발송).
    row_numbers 를 주면 그 행들의 문안을, 생략하면 문제없는 첫 수신자 하나의 문안을 돌려준다.
    수신자마다 맞춤 내용을 썼다면 모든 행 번호를 넣어 전부 검토한다."""
    body = campaign(template, list_name, subject)
    p = api("POST", "/api/prepare", body)
    issues, ok_rows, omitted = [], [], []
    for r in p["recipients"]:
        if r["omitted"]:
            omitted.append({"row_number": r["idx"] + 1, "fields": r["omitted"]})
        problems = (["주소 오류"] if r["invalid"] else []) + (["리스트 내 중복"] if r["duplicate"] else []) \
            + (["이전에 발송한 주소"] if r["already_sent"] else []) + [f"빈 값: {m}" for m in r["missing"]]
        if problems:
            issues.append({"row_number": r["idx"] + 1, "email": r["email"], "problems": problems})
        else:
            ok_rows.append(r["idx"] + 1)
    samples = []
    for n in row_numbers or [ok_rows[0] if ok_rows else 1]:
        rendered = api("POST", "/api/render", {**body, "idx": n - 1})
        samples.append({"row_number": n, "subject": rendered["subject"], "body": mailer.html_to_text(rendered["html"])})
    return {"recipients": len(p["recipients"]), "ready": len(ok_rows), "issues": issues,
            "omitted_paragraphs": omitted,  # 비어 있어서 빠지는 맞춤문단(문제 아님, 의도한 것인지 확인용)
            "unknown_fields": p["unknown"], "samples": samples}


@mcp.tool()
def send_test(template: str, list_name: str, subject: str, row_number: int = 1,
              attachments: list[str] | None = None) -> dict:
    """해당 행 기준으로 만든 메일을 '보내는 사람 본인 주소'로만 테스트 발송한다 (제목 앞에 [테스트])."""
    r = api("POST", "/api/test-send", {**campaign(template, list_name, subject), "idx": row_number - 1,
                                       "attachments": attachments or []})
    return {"sent_to": r["to"]}


@mcp.tool()
def queue_campaign(template: str, list_name: str, subject: str, attachments: list[str] | None = None,
                   row_numbers: list[int] | None = None, note: str = "") -> dict:
    """발송을 '발송 대기'에 올린다. 실제 발송은 사용자가 앱의 발송 탭에서 확인하고 직접 누른다.
    row_numbers 를 주면 그 행들만, 생략하면 문제없는 전체 수신자가 기본 선택된다. note 는 사용자에게 보일 메모."""
    item = api("POST", "/api/queue", {**campaign(template, list_name, subject), "attachments": attachments or [],
                                      "indices": [n - 1 for n in row_numbers] if row_numbers else None, "note": note})
    return {"queued": item, "next_step": "사용자에게 바탕화면의 'ColdMail Sender' 앱 → 발송 탭 → 발송 대기에서 "
                                         "불러오기 → 확인 후 발송 시작을 누르도록 안내하세요."}


@mcp.tool()
def send_history(email_contains: str = "", limit: int = 50) -> list[dict]:
    """발송 기록(최신순). email_contains 로 주소 일부를 검색해 이미 연락한 사람인지 확인할 수 있다."""
    rows = [r for r in api("GET", "/api/log") if email_contains.lower() in r["email"].lower()]
    return [{k: r[k] for k in ("ts", "status", "email", "label", "subject", "error")} for r in rows[:limit]]


if __name__ == "__main__":
    mcp.run()
