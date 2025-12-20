# POCTraderBR


VS Code에서 python으로 poc작업을 하려고 해, 폴더까지는 생성해서 열었고, venv를 설정하고 싶어

아래 순서대로 하면 VS Code에서 프로젝트 전용 venv(가상환경) 를 만들고, VS Code가 그 venv를 자동으로 사용하도록 설정할 수 있습니다. (Windows 기준, 현재 상황: 폴더 생성/열기까지 완료)

아래 순서대로 하면 VS Code에서 **프로젝트 전용 venv(가상환경)** 를 만들고, VS Code가 그 venv를 자동으로 사용하도록 설정할 수 있습니다. (Windows 기준, 현재 상황: 폴더 생성/열기까지 완료)

---

## 1) PowerShell 실행 정책 때문에 Activate가 막히는 경우 먼저 해결

이전에 `Activate.ps1` 실행이 막혔던 로그가 있었으니(“스크립트를 실행할 수 없음”), 먼저 아래를 1회만 해두는 게 안전합니다.

1. VS Code에서 **Terminal** 열기
2. PowerShell에서 아래 실행

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

* `CurrentUser` 범위만 바꾸는 거라 시스템 전체에 영향이 적습니다.

---

## 2) venv 생성 (프로젝트 루트에서)

프로젝트 폴더(루트)에서 터미널을 열고 아래 중 하나로 생성합니다.

### 방법 A) python이 PATH에 잡혀있는 경우

```powershell
python -m venv .venv
```

### 방법 B) VS Code가 선택한 python으로 확실히 만들기

VS Code에서 `Ctrl+Shift+P` → **Python: Select Interpreter**에서 원하는 Python(예: 시스템 Python) 선택 후,
터미널에서:

```powershell
py -m venv .venv
```

생성되면 폴더에 `.venv/` 가 생깁니다.

---

## 3) venv 활성화

PowerShell 기준:

```powershell
.\.venv\Scripts\Activate.ps1
```

정상이라면 프롬프트 앞에 `(.venv)` 표시가 붙습니다.

활성화가 귀찮으면(그리고 정책 문제도 회피하려면) **굳이 activate 안 하고도** 아래처럼 venv의 python 경로를 직접 써도 됩니다:

```powershell
.\.venv\Scripts\python.exe -m pip --version
```

---

## 4) VS Code에 venv 인터프리터 연결 (가장 중요)

1. `Ctrl+Shift+P`
2. **Python: Select Interpreter**
3. 목록에서 `.\.venv\Scripts\python.exe` (또는 `.venv`가 붙은 항목) 선택

선택 후, VS Code 오른쪽 아래(또는 상태바)에 인터프리터가 `.venv`로 표시되어야 합니다.

---

## 5) pip 업그레이드 + 필수 패키지 설치 (venv에 설치)

venv 활성화 상태라면:

```powershell
python -m pip install --upgrade pip
python -m pip install -U wheel setuptools
```

프로젝트에서 필요한 패키지(예: requests 등)도 같은 방식으로 설치합니다:

```powershell
python -m pip install requests
```

---

## 6) 실행/디버깅이 venv로 도는지 확인

프로젝트에 `test_env.py` 만들어서 아래 작성:

```python
import sys
print(sys.executable)
```

실행했을 때 출력 경로가 `...\프로젝트\.venv\Scripts\python.exe` 로 나오면 성공입니다.

---

## 7) 권장: requirements.txt 관리

나중에 재현성/공유를 위해:

```powershell
python -m pip freeze > requirements.txt
```

다른 PC에서 복원할 때는:

```powershell
python -m pip install -r requirements.txt
```

---

## 자주 터지는 포인트 3개

1. **VS Code가 다른 Python을 계속 잡는 문제**
   → 반드시 “Python: Select Interpreter”에서 `.venv`를 찍어야 합니다.

2. **터미널은 venv인데, 디버그는 시스템 python으로 실행되는 문제**
   → `.vscode/launch.json`에서 interpreter가 꼬였거나, 인터프리터 선택이 반영 안 된 경우가 많습니다. (대부분 4번만 제대로 하면 해결)

3. **Activate.ps1 정책 에러**
   → 1번 RemoteSigned로 해결되는 경우가 대부분입니다.

---

원하시면, 지금 프로젝트 폴더 구조(루트 경로)와 터미널에서 아래 두 줄 실행 결과만 붙여주시면, **현재 VS Code가 어떤 인터프리터를 쓰고 있는지**까지 정확히 짚어서 바로 잡아드릴게요.

```powershell
python --version
python -c "import sys; print(sys.executable)"
```
