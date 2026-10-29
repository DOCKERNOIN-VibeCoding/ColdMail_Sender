# ColdMail Sender

협업·영업 제안 메일머지 앱. 사용법·구성은 README.md 참고.
다른 폴더의 Claude 세션은 이 파일을 보지 못한다. 그쪽에 전달되는 사용 규칙은 `mcp_server.py` 의 `INSTRUCTIONS`
(MCP 서버 안내문)이므로, 아래 '메일 작업' 규칙을 바꾸면 INSTRUCTIONS 와 README 도 함께 고친다.

## 메일 작업을 도울 때

- `coldmail-sender` MCP 도구를 쓴다: overview → send_history → save_list / save_template → preview → send_test → queue_campaign.
- **대량 발송은 사람이 한다.** queue_campaign 으로 '발송 대기'에 올리고, 사용자에게 앱의 발송 탭에서
  확인 후 발송하라고 안내한다. 앱 서버 API(`/api/send`)를 curl 등으로 직접 호출해 발송하지 않는다.
- 연락 전 send_history 로 이미 보낸 사람인지 확인한다.
- 열 이름은 자유다(채널명/이름, 회사명/담당자명 등). '이메일' 열만 필수.

### 수신자마다 다른 내용 (맞춤 문단)

- 맞춤 내용은 **리스트의 열**(예: `맞춤문단 1`~`맞춤문단 5`, `제목`)에 넣고, 템플릿은 공통 틀만 둔다. 수신자별 md 파일을 만들지 않는다.
- 템플릿: 각 `{{맞춤문단 N}}` 을 빈 줄로 띄운 단독 문단으로 배치. 권장: 1 연락 계기 / 2 제안 아이디어 / 3 기대 효과 /
  공통 소개·조건 / 4 조건·일정 개별 메모 / 5 마무리 한마디 / 서명. 통째로 다르면 `{{본문}}` + 서명.
- `맞춤문단`으로 시작하는 열은 **선택 항목**: 비면 그 문단이 통째로 빠지고 발송 대상에서도 제외되지 않는다
  (`mailer.is_optional`, `drop_empty_optional`). 다른 열이 비면 '빈 값' 문제로 잡힌다.
- 열 이름과 `{{ }}` 이름은 띄어쓰기까지 정확히 같아야 한다(`맞춤문단 1` ≠ `맞춤문단1`).
- 발송 제목에 `{{제목}}` 처럼 열을 넣으면 제목도 수신자마다 달라진다.
- 열 값은 일반 텍스트: `\n` 은 메일에서 줄바꿈, `\n\n` 은 문단 간격. 마크다운은 적용되지 않는다(글자 그대로 보임).
- 열 값 안의 조사는 자동 교정되지 않으니 직접 맞게 쓴다. 제목 열의 줄바꿈은 공백이 된다.
- 맞춤 내용을 썼으면 preview(row_numbers=[모든 행]) 로 전부 검토하고, omitted_paragraphs(생략되는 맞춤문단)가
  의도한 것인지 확인한 뒤 queue_campaign 한다.
- 버전이 몇 개뿐이면 버전별 템플릿 + queue_campaign(row_numbers=...) 를 버전마다.
- 형식 참고: `samples/협업제안_맞춤형.md` + `samples/수신자리스트_샘플.xlsx`(맞춤문단 1~5 열).

### 자동 처리 (템플릿의 `{{열이름}}` 바로 뒤)

- 조사 자동 교정: `{{채널명}}가` → 쯔양이 / 안원잘부가. 영어 값은 틀릴 수 있으니 preview 로 확인.
- 이름 합치기: `{{채널명}} {{이름}} 님` 은 두 값이 사실상 같으면(고재영TV/고재영) `고재영 님`.

## 코드를 고칠 때

- `.bat` 파일은 ASCII 만 쓴다. cmd 가 CP949 로 읽어 한글이 다음 줄까지 깨뜨린다.
- MCP 서버는 앱 서버를 띄우지 않는다. MCP 클라이언트가 세션 종료 시 하위 프로세스를 Job 으로 모두 죽이므로,
  그 서버로 진행 중인 발송이 끊긴다. 그래서 `app.app.test_client()` 로 API 를 프로세스 안에서 호출한다.
- MCP 도구 오류는 `ToolError` 로 올린다. 다른 예외는 mcp 2.x 가 메시지를 숨긴다.
- 비밀번호는 keyring(Windows 자격 증명 관리자)에만 둔다. 파일·로그·출력에 쓰지 않는다.
- 앱 표의 칸은 `<input>` 이라 줄바꿈을 지운다. 여러 줄 값은 읽기 전용 칸 + 편집창(dialog)으로만 고친다.
- 테스트는 `COLDMAIL_DATA`(데이터 폴더)와 `COLDMAIL_PORT` 환경변수로 실제 데이터와 분리해서 돌린다.
- 가상환경: `%LOCALAPPDATA%\ColdMailSender\venv` (Python 3.14). 서버 로그: `%LOCALAPPDATA%\ColdMailSender\server.log`.
- 동료 배포는 설치판(`build.bat` → PyInstaller + Inno Setup). exe 진입점은 `launcher.pyw` 이고 인자로 역할을 나눈다
  (`--server` / `--mcp` / `--register-mcp` / `--unregister-mcp`). 설치판(`sys.frozen`)은 데이터를 `%LOCALAPPDATA%\ColdMailSender\data` 에 둔다.
  동적으로 import 되는 패키지나 새 데이터 폴더를 추가하면 `build.bat` 의 `--collect-submodules`/`--add-data` 도 고친다.
- 개발 PC에서 설치 파일을 실행하지 않는다(사용자의 Claude MCP 등록이 설치판으로 바뀐다). exe 는 `COLDMAIL_DATA`·`COLDMAIL_PORT` 로 분리해 시험한다.

## 샘플 파일

`samples/` 는 첫 실행 시 앱에 들어가는 샘플이다(`store.seed_samples`, `data/.samples_added` 로 한 번만).
샘플 주소는 반드시 `@example.com` 으로 두고, 실존 인물 이름을 쓰지 않는다.
