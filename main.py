import ast
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import traceback
from urllib.parse import urlparse

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SITES_DIR = os.path.join(BASE_DIR, "saved_sites")
CHATS_DIR = os.path.join(BASE_DIR, "chats")
SCRIPTS_DIR = os.path.join(BASE_DIR, "saved_scripts")

# ---------------------------------------------------------
# LOCAL AI SERVER
# ---------------------------------------------------------

LOCAL_API_URL = os.getenv(
    "LOCAL_API_URL",
    "http://127.0.0.1:8080/v1"
).rstrip("/")

# ВАЖНО:
# Раньше здесь была ошибка:
#
# os.getenv("qwen2.5-3b", ...)
#
# Теперь используется нормальная переменная окружения MODEL_NAME.

MODEL_NAME = os.getenv(
    "MODEL_NAME",
    "qwen2.5-3b-instruct-q8_0"
)

# Для локального OpenAI-compatible сервера настоящий
# API key часто вообще не нужен.
#
# Если сервер требует ключ:
#
# Windows CMD:
#   set LOCAL_API_KEY=your_key
#
# PowerShell:
#   $env:LOCAL_API_KEY="your_key"
#
# Не храни настоящий ключ прямо в коде.

API_KEY = "sXjpYRX2urzUJjLTxad4GdVf9xdZX3"

# ---------------------------------------------------------
# BROWSER
# ---------------------------------------------------------

BRAVE_PATH = os.getenv(
    "BRAVE_PATH",
    r"C:\Program Files\BraveSoftware\Brave-Browser\brave.exe"
)

# ---------------------------------------------------------
# LIMITS
# ---------------------------------------------------------

MAX_TOOL_STEPS = 100
MAX_AUTO_FIX_ATTEMPTS = 15

SCRIPT_TIMEOUT = 300      # 5 минут
PIP_TIMEOUT = 600         # 10 минут

MAX_OUTPUT = 50000
MAX_CODE_SIZE = 500000

API_CONNECT_TIMEOUT = 5


os.makedirs(SITES_DIR, exist_ok=True)
os.makedirs(CHATS_DIR, exist_ok=True)
os.makedirs(SCRIPTS_DIR, exist_ok=True)


# =========================================================
# COLORS
# =========================================================

RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GRAY = "\033[90m"


def color(text, color_code):
    return f"{color_code}{text}{RESET}"


# =========================================================
# LOGGING
# =========================================================

def log(text):
    print(text, flush=True)


def log_info(text):
    print(
        color(
            f"[INFO] {text}",
            CYAN
        ),
        flush=True
    )


def log_success(text):
    print(
        color(
            f"[OK] {text}",
            GREEN
        ),
        flush=True
    )


def log_warning(text):
    print(
        color(
            f"[WARNING] {text}",
            YELLOW
        ),
        flush=True
    )


def log_error(text):
    print(
        color(
            f"[ERROR] {text}",
            RED
        ),
        flush=True
    )


def log_ai(text):
    print(
        color(
            f"[AI STATUS] {text}",
            MAGENTA
        ),
        flush=True
    )


def log_tool(name):
    print(
        color(
            f"[TOOL] {name}",
            BLUE
        ),
        flush=True
    )


def log_step(step, total):
    print(
        color(
            f"\n[AI STEP {step}/{total}]",
            MAGENTA
        ),
        flush=True
    )


# =========================================================
# TEXT UTILITIES
# =========================================================

def truncate_text(text, limit=MAX_OUTPUT):

    if text is None:
        return ""

    text = str(text)

    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + "\n\n...[OUTPUT TRUNCATED]..."
    )


def pretty_json(data):

    try:
        return json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        )
    except Exception:
        return str(data)


# =========================================================
# API CONFIGURATION
# =========================================================

def get_api_host_port():

    try:

        parsed = urlparse(
            LOCAL_API_URL
        )

        host = parsed.hostname

        port = parsed.port

        if port is None:

            if parsed.scheme == "https":
                port = 443
            else:
                port = 80

        return host, port

    except Exception:

        return None, None


def check_api_connection():

    host, port = get_api_host_port()

    if not host or not port:

        log_error(
            f"Некорректный LOCAL_API_URL: "
            f"{LOCAL_API_URL}"
        )

        return False

    log_info(
        f"Проверка подключения к "
        f"{host}:{port} ..."
    )

    try:

        with socket.create_connection(
            (host, port),
            timeout=API_CONNECT_TIMEOUT
        ):

            pass

        log_success(
            f"Порт {host}:{port} доступен."
        )

        return True

    except ConnectionRefusedError:

        log_error(
            f"Подключение к {host}:{port} "
            f"отклонено."
        )

        print()
        print(
            "Локальный AI-сервер, скорее всего, "
            "не запущен."
        )
        print()
        print(
            "Текущий API:"
        )
        print(
            f"  {LOCAL_API_URL}"
        )
        print(
            f"Текущая модель:"
        )
        print(
            f"  {MODEL_NAME}"
        )
        print()
        print(
            "Запусти свой OpenAI-compatible сервер "
            "на этом адресе/порту или измени:"
        )
        print(
            "  LOCAL_API_URL"
        )
        print()

        return False

    except TimeoutError:

        log_error(
            f"Таймаут подключения к "
            f"{host}:{port}."
        )

        return False

    except OSError as e:

        log_error(
            f"Ошибка подключения к "
            f"{host}:{port}: {e}"
        )

        return False

    except Exception as e:

        log_error(
            f"Не удалось проверить API: "
            f"{type(e).__name__}: {e}"
        )

        return False


# =========================================================
# OPENAI CLIENT
# =========================================================

client = None

if OpenAI is not None:

    try:

        client = OpenAI(
            base_url=LOCAL_API_URL,
            api_key=API_KEY
        )

        log_success(
            "OpenAI-compatible client создан."
        )

    except Exception as e:

        log_error(
            f"Ошибка создания OpenAI client: "
            f"{type(e).__name__}: {e}"
        )

else:

    log_error(
        "Пакет openai не установлен."
    )


# =========================================================
# PACKAGE MAP
# =========================================================

PIP_PACKAGE_MAP = {

    "deep_translator":
        "deep-translator",

    "PIL":
        "Pillow",

    "cv2":
        "opencv-python",

    "bs4":
        "beautifulsoup4",

    "sklearn":
        "scikit-learn",

    "yaml":
        "PyYAML",

    "dotenv":
        "python-dotenv",

    "dateutil":
        "python-dateutil",

    "serial":
        "pyserial",

    "requests":
        "requests",

    "numpy":
        "numpy",

    "pandas":
        "pandas",

    "openpyxl":
        "openpyxl",

    "lxml":
        "lxml",

    "selenium":
        "selenium",

    "playwright":
        "playwright",

    "flask":
        "Flask",

    "django":
        "Django",

    "fastapi":
        "fastapi",

    "uvicorn":
        "uvicorn",

    "aiohttp":
        "aiohttp",

    "httpx":
        "httpx",

    "jinja2":
        "Jinja2",

    "rich":
        "rich",

    "colorama":
        "colorama",

    "pyautogui":
        "PyAutoGUI",

    "keyboard":
        "keyboard",

    "pyperclip":
        "pyperclip",

    "pytz":
        "pytz",

    "jwt":
        "PyJWT",

    "cryptography":
        "cryptography",

    "telegram":
        "python-telegram-bot",

    "discord":
        "discord.py",
}


# =========================================================
# STANDARD LIBRARY
# =========================================================

STANDARD_LIBRARY_MODULES = {

    "abc",
    "argparse",
    "array",
    "ast",
    "asyncio",
    "base64",
    "binascii",
    "bisect",
    "builtins",
    "calendar",
    "cmath",
    "cmd",
    "codecs",
    "collections",
    "concurrent",
    "configparser",
    "contextlib",
    "copy",
    "csv",
    "ctypes",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "dis",
    "email",
    "enum",
    "errno",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "imaplib",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "math",
    "mimetypes",
    "multiprocessing",
    "numbers",
    "operator",
    "os",
    "pathlib",
    "pickle",
    "platform",
    "plistlib",
    "pprint",
    "profile",
    "pstats",
    "queue",
    "random",
    "re",
    "secrets",
    "select",
    "selectors",
    "shlex",
    "shutil",
    "signal",
    "site",
    "socket",
    "sqlite3",
    "ssl",
    "statistics",
    "string",
    "struct",
    "subprocess",
    "sys",
    "symtable",
    "tempfile",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "traceback",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uuid",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "xml",
    "xmlrpc",
    "zipfile",
    "zipimport",
    "zlib"
}


# =========================================================
# PYTHON ANALYSIS
# =========================================================

def module_to_package(module_name):

    root = str(
        module_name
    ).strip().split(".")[0]

    return PIP_PACKAGE_MAP.get(
        root,
        root
    )


def is_module_installed(module_name):

    root = str(
        module_name
    ).split(".")[0]

    try:

        return (
            importlib.util.find_spec(root)
            is not None
        )

    except Exception:

        return False


def check_python_syntax(code):

    try:

        ast.parse(code)

        return {
            "status": "success",
            "message": "Syntax is valid."
        }

    except SyntaxError as e:

        return {
            "status": "error",
            "error_type": "SyntaxError",
            "message": str(e),
            "line": e.lineno,
            "column": e.offset,
            "text": e.text
        }

    except Exception as e:

        return {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e)
        }


def extract_imports_from_code(code):

    imports = set()

    try:

        tree = ast.parse(code)

    except SyntaxError:

        return []

    for node in ast.walk(tree):

        if isinstance(
            node,
            ast.Import
        ):

            for alias in node.names:

                imports.add(
                    alias.name.split(".")[0]
                )

        elif isinstance(
            node,
            ast.ImportFrom
        ):

            if node.module:

                imports.add(
                    node.module.split(".")[0]
                )

    return sorted(imports)


def find_missing_modules(code):

    imports = extract_imports_from_code(
        code
    )

    missing = []

    for module_name in imports:

        if (
            module_name
            in STANDARD_LIBRARY_MODULES
        ):
            continue

        if module_name == "__future__":
            continue

        if not is_module_installed(
            module_name
        ):

            missing.append({
                "module": module_name,
                "package":
                    module_to_package(
                        module_name
                    )
            })

    return missing


def detect_error_type(stderr):

    if not stderr:
        return "UnknownError"

    known_errors = [

        "ModuleNotFoundError",
        "ImportError",
        "SyntaxError",
        "NameError",
        "TypeError",
        "ValueError",
        "AttributeError",
        "FileNotFoundError",
        "PermissionError",
        "KeyError",
        "IndexError",
        "RuntimeError",
        "TimeoutError",
        "ConnectionError",
        "OSError",
        "JSONDecodeError",
        "ZeroDivisionError",
        "AssertionError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "NotImplementedError",
    ]

    for error_name in known_errors:

        if error_name in stderr:
            return error_name

    return "RuntimeError"


def extract_missing_module_from_error(
    stderr
):

    if not stderr:
        return None

    patterns = [

        r"No module named ['\"]([^'\"]+)['\"]",

        r"No module named "
        r"([A-Za-z0-9_.-]+)"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            stderr
        )

        if match:

            return (
                match.group(1)
                .split(".")[0]
            )

    return None


# =========================================================
# PIP
# =========================================================

def install_python_package(
    package_name
):

    package_name = str(
        package_name
    ).strip()

    clean_name = re.sub(
        r"[^a-zA-Z0-9_.<>=!~\-\[\],@:/]+",
        "",
        package_name
    )

    if not clean_name:

        return {
            "status": "error",
            "error_type":
                "InvalidPackageName",
            "message":
                "Invalid package name."
        }

    log_info(
        f"Устанавливаю пакет: "
        f"{clean_name}"
    )

    try:

        process = subprocess.run(

            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                clean_name
            ],

            capture_output=True,

            text=True,

            encoding="utf-8",

            errors="replace",

            timeout=PIP_TIMEOUT,

            env={
                **os.environ,
                "PYTHONIOENCODING":
                    "utf-8"
            }
        )

        stdout = (
            process.stdout
            or ""
        )

        stderr = (
            process.stderr
            or ""
        )

        if process.returncode == 0:

            log_success(
                f"Пакет установлен: "
                f"{clean_name}"
            )

            return {

                "status":
                    "success",

                "package_name":
                    clean_name,

                "stdout":
                    truncate_text(
                        stdout
                    ),

                "stderr":
                    truncate_text(
                        stderr
                    )
            }

        log_error(
            f"Ошибка pip install "
            f"{clean_name}"
        )

        print(
            truncate_text(
                stderr
            )
        )

        return {

            "status":
                "error",

            "error_type":
                "PipInstallError",

            "package_name":
                clean_name,

            "stdout":
                truncate_text(
                    stdout
                ),

            "stderr":
                truncate_text(
                    stderr
                ),

            "returncode":
                process.returncode
        }

    except subprocess.TimeoutExpired:

        log_error(
            f"Установка {clean_name} "
            f"превысила {PIP_TIMEOUT} секунд."
        )

        return {

            "status":
                "error",

            "error_type":
                "PipTimeout",

            "message":
                f"Installation exceeded "
                f"{PIP_TIMEOUT} seconds."
        }

    except Exception as e:

        log_error(
            f"Ошибка установки пакета: "
            f"{type(e).__name__}: {e}"
        )

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }


# =========================================================
# EXECUTE PYTHON CODE
# =========================================================

def execute_python_code(code):

    log_info(
        "Проверяю Python-код..."
    )

    syntax = check_python_syntax(
        code
    )

    if syntax["status"] == "error":

        log_error(
            "SyntaxError при проверке кода."
        )

        print(
            pretty_json(
                syntax
            )
        )

        return {

            "status":
                "error",

            "error_type":
                "SyntaxError",

            "details":
                syntax
        }

    path = None

    try:

        with tempfile.NamedTemporaryFile(

            "w",

            suffix=".py",

            delete=False,

            encoding="utf-8"

        ) as f:

            f.write(code)

            path = f.name

        process = subprocess.run(

            [
                sys.executable,
                path
            ],

            capture_output=True,

            text=True,

            encoding="utf-8",

            errors="replace",

            timeout=SCRIPT_TIMEOUT,

            cwd=BASE_DIR,

            env={
                **os.environ,
                "PYTHONIOENCODING":
                    "utf-8"
            }
        )

        stdout = (
            process.stdout
            or ""
        )

        stderr = (
            process.stderr
            or ""
        )

        result = {

            "status": (
                "success"
                if process.returncode == 0
                else "error"
            ),

            "python":
                sys.executable,

            "returncode":
                process.returncode,

            "stdout":
                truncate_text(
                    stdout
                ),

            "stderr":
                truncate_text(
                    stderr
                )
        }

        if process.returncode != 0:

            result["error_type"] = (
                detect_error_type(
                    stderr
                )
            )

            log_error(
                "Python-код завершился "
                f"с кодом {process.returncode}."
            )

            if stderr:

                print(
                    color(
                        stderr,
                        RED
                    )
                )

        else:

            log_success(
                "Python-код выполнен успешно."
            )

            if stdout:

                print(
                    color(
                        stdout,
                        GREEN
                    )
                )

        return result

    except subprocess.TimeoutExpired:

        log_error(
            f"Код превысил лимит "
            f"{SCRIPT_TIMEOUT} секунд."
        )

        return {

            "status":
                "error",

            "error_type":
                "TimeoutExpired",

            "message":
                f"Code exceeded "
                f"{SCRIPT_TIMEOUT} seconds."
        }

    except Exception as e:

        log_error(
            f"{type(e).__name__}: {e}"
        )

        print(
            traceback.format_exc()
        )

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }

    finally:

        if path and os.path.exists(path):

            try:

                os.remove(path)

            except Exception:

                pass


# =========================================================
# SCRIPT PATH
# =========================================================

def safe_script_path(
    script_name
):

    script_name = str(
        script_name
    ).strip()

    script_name = script_name.replace(
        "\\",
        "/"
    )

    script_name = os.path.basename(
        script_name
    )

    if not script_name.lower().endswith(
        ".py"
    ):

        script_name += ".py"

    script_name = re.sub(
        r"[^\w\-.]",
        "_",
        script_name
    )

    return os.path.join(
        SCRIPTS_DIR,
        script_name
    )


# =========================================================
# READ SCRIPT
# =========================================================

def read_python_script(
    script_name
):

    filepath = safe_script_path(
        script_name
    )

    if not os.path.exists(filepath):

        return {

            "status":
                "error",

            "error_type":
                "ScriptNotFound",

            "message":
                f"File not found: "
                f"{filepath}"
        }

    try:

        with open(

            filepath,

            "r",

            encoding="utf-8"

        ) as f:

            code = f.read()

        if len(code) > MAX_CODE_SIZE:

            return {

                "status":
                    "error",

                "error_type":
                    "CodeTooLarge",

                "message":
                    f"Script is larger than "
                    f"{MAX_CODE_SIZE} characters."
            }

        return {

            "status":
                "success",

            "script_name":
                os.path.basename(
                    filepath
                ),

            "path":
                os.path.abspath(
                    filepath
                ),

            "code":
                code
        }

    except Exception as e:

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }


# =========================================================
# SAVE SCRIPT
# =========================================================

def save_python_script(
    script_name,
    code,
    description=""
):

    if not code.strip():

        return {

            "status":
                "error",

            "error_type":
                "EmptyCode",

            "message":
                "Code is empty."
        }

    if len(code) > MAX_CODE_SIZE:

        return {

            "status":
                "error",

            "error_type":
                "CodeTooLarge",

            "message":
                f"Code is larger than "
                f"{MAX_CODE_SIZE} characters."
        }

    syntax = check_python_syntax(
        code
    )

    if syntax["status"] == "error":

        return {

            "status":
                "error",

            "error_type":
                "SyntaxError",

            "details":
                syntax
        }

    filepath = safe_script_path(
        script_name
    )

    try:

        if description:

            final_code = (
                '"""\n'
                f"Description: {description}\n"
                '"""\n\n'
                + code
            )

        else:

            final_code = code

        with open(

            filepath,

            "w",

            encoding="utf-8"

        ) as f:

            f.write(
                final_code
            )

        log_success(
            f"Скрипт сохранён: "
            f"{os.path.basename(filepath)}"
        )

        return {

            "status":
                "success",

            "script_name":
                os.path.basename(
                    filepath
                ),

            "path":
                os.path.abspath(
                    filepath
                ),

            "message":
                "Script saved."
        }

    except Exception as e:

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }


# =========================================================
# UPDATE SCRIPT
# =========================================================

def update_python_script(
    script_name,
    code
):

    filepath = safe_script_path(
        script_name
    )

    if not os.path.exists(filepath):

        return {

            "status":
                "error",

            "error_type":
                "ScriptNotFound",

            "message":
                f"File not found: "
                f"{filepath}"
        }

    if not code.strip():

        return {

            "status":
                "error",

            "error_type":
                "EmptyCode",

            "message":
                "Code is empty."
        }

    if len(code) > MAX_CODE_SIZE:

        return {

            "status":
                "error",

            "error_type":
                "CodeTooLarge",

            "message":
                f"Code is larger than "
                f"{MAX_CODE_SIZE} characters."
        }

    syntax = check_python_syntax(
        code
    )

    if syntax["status"] == "error":

        return {

            "status":
                "error",

            "error_type":
                "SyntaxError",

            "details":
                syntax
        }

    try:

        with open(

            filepath,

            "w",

            encoding="utf-8"

        ) as f:

            f.write(code)

        log_success(
            f"Скрипт обновлён: "
            f"{os.path.basename(filepath)}"
        )

        return {

            "status":
                "success",

            "script_name":
                os.path.basename(
                    filepath
                ),

            "path":
                os.path.abspath(
                    filepath
                ),

            "message":
                "Script updated successfully."
        }

    except Exception as e:

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }


# =========================================================
# LIST SCRIPTS
# =========================================================

def list_saved_scripts():

    if not os.path.exists(
        SCRIPTS_DIR
    ):

        return []

    return sorted(

        filename

        for filename
        in os.listdir(
            SCRIPTS_DIR
        )

        if filename.endswith(
            ".py"
        )
    )


# =========================================================
# RUN SAVED SCRIPT
# =========================================================

def run_saved_script(
    script_name,
    args=None
):

    filepath = safe_script_path(
        script_name
    )

    if not os.path.exists(filepath):

        return {

            "status":
                "error",

            "error_type":
                "ScriptNotFound",

            "message":
                f"File not found: "
                f"{filepath}"
        }

    if args is None:
        args = []

    args = [
        str(x)
        for x in args
    ]

    try:

        with open(

            filepath,

            "r",

            encoding="utf-8"

        ) as f:

            code = f.read()

    except Exception as e:

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e)
        }

    syntax = check_python_syntax(
        code
    )

    if syntax["status"] == "error":

        log_error(
            "SyntaxError перед запуском."
        )

        print(
            pretty_json(
                syntax
            )
        )

        return {

            "status":
                "error",

            "error_type":
                "SyntaxError",

            "details":
                syntax
        }

    installed_packages = []

    missing_modules = find_missing_modules(
        code
    )

    for missing in missing_modules:

        module_name = missing["module"]

        package_name = missing["package"]

        log_info(
            f"Найдена зависимость: "
            f"{module_name} -> {package_name}"
        )

        install_result = (
            install_python_package(
                package_name
            )
        )

        if install_result["status"] != "success":

            return {

                "status":
                    "error",

                "error_type":
                    "DependencyInstallError",

                "missing_module":
                    module_name,

                "package":
                    package_name,

                "install_result":
                    install_result
            }

        installed_packages.append(
            package_name
        )

    cmd = [

        sys.executable,

        filepath,

        *args
    ]

    log_info(
        f"Запуск: "
        f"{os.path.basename(filepath)}"
    )

    if args:

        log_info(
            f"Аргументы: {args}"
        )

    try:

        process = subprocess.run(

            cmd,

            capture_output=True,

            text=True,

            encoding="utf-8",

            errors="replace",

            timeout=SCRIPT_TIMEOUT,

            cwd=SCRIPTS_DIR,

            env={
                **os.environ,
                "PYTHONIOENCODING":
                    "utf-8"
            }
        )

        stdout = (
            process.stdout
            or ""
        )

        stderr = (
            process.stderr
            or ""
        )

        result = {

            "status": (

                "success"

                if process.returncode == 0

                else "error"
            ),

            "script_name":
                os.path.basename(
                    filepath
                ),

            "args":
                args,

            "python":
                sys.executable,

            "returncode":
                process.returncode,

            "stdout":
                truncate_text(
                    stdout
                ),

            "stderr":
                truncate_text(
                    stderr
                ),

            "installed_packages":
                installed_packages
        }

        if process.returncode == 0:

            log_success(
                f"Скрипт завершился успешно "
                f"(returncode=0)"
            )

            if stdout:

                print(
                    color(
                        "\n--- STDOUT ---\n"
                        + truncate_text(
                            stdout
                        ),
                        GREEN
                    )
                )

            if stderr:

                print(
                    color(
                        "\n--- STDERR ---\n"
                        + truncate_text(
                            stderr
                        ),
                        YELLOW
                    )
                )

            return result

        # -------------------------------------------------
        # ERROR
        # -------------------------------------------------

        error_type = detect_error_type(
            stderr
        )

        result["error_type"] = (
            error_type
        )

        log_error(
            f"Скрипт завершился с ошибкой."
        )

        log_error(
            f"returncode = "
            f"{process.returncode}"
        )

        log_error(
            f"error_type = "
            f"{error_type}"
        )

        if stdout:

            print()
            print(
                color(
                    "--- STDOUT ---",
                    CYAN
                )
            )
            print(stdout)

        if stderr:

            print()
            print(
                color(
                    "--- STDERR / TRACEBACK ---",
                    RED
                )
            )
            print(stderr)

        missing_module = (
            extract_missing_module_from_error(
                stderr
            )
        )

        # -------------------------------------------------
        # AUTOMATIC MISSING MODULE INSTALL
        # -------------------------------------------------

        if (
            error_type
            == "ModuleNotFoundError"
            and missing_module
        ):

            package_name = (
                module_to_package(
                    missing_module
                )
            )

            log_warning(
                f"Отсутствует модуль: "
                f"{missing_module}"
            )

            log_info(
                f"Пробую установить: "
                f"{package_name}"
            )

            install_result = (
                install_python_package(
                    package_name
                )
            )

            result[
                "dependency_install"
            ] = install_result

            if (
                install_result["status"]
                == "success"
            ):

                log_ai(
                    "Зависимость установлена. "
                    "Повторяю запуск."
                )

                retry = subprocess.run(

                    cmd,

                    capture_output=True,

                    text=True,

                    encoding="utf-8",

                    errors="replace",

                    timeout=SCRIPT_TIMEOUT,

                    cwd=SCRIPTS_DIR,

                    env={
                        **os.environ,
                        "PYTHONIOENCODING":
                            "utf-8"
                    }
                )

                retry_stdout = (
                    retry.stdout
                    or ""
                )

                retry_stderr = (
                    retry.stderr
                    or ""
                )

                result["retry"] = {

                    "returncode":
                        retry.returncode,

                    "stdout":
                        truncate_text(
                            retry_stdout
                        ),

                    "stderr":
                        truncate_text(
                            retry_stderr
                        )
                }

                if retry.returncode == 0:

                    result["status"] = (
                        "success"
                    )

                    result["returncode"] = 0

                    result["stdout"] = (
                        truncate_text(
                            retry_stdout
                        )
                    )

                    result["stderr"] = (
                        truncate_text(
                            retry_stderr
                        )
                    )

                    log_success(
                        "Повторный запуск "
                        "успешен."
                    )

                else:

                    result[
                        "returncode"
                    ] = retry.returncode

                    result["stdout"] = (
                        truncate_text(
                            retry_stdout
                        )
                    )

                    result["stderr"] = (
                        truncate_text(
                            retry_stderr
                        )
                    )

                    result[
                        "error_type"
                    ] = detect_error_type(
                        retry_stderr
                    )

                    log_error(
                        "Повторный запуск "
                        "тоже завершился ошибкой."
                    )

                    print(
                        color(
                            retry_stderr,
                            RED
                        )
                    )

        return result

    except subprocess.TimeoutExpired:

        log_error(
            f"Скрипт превысил "
            f"{SCRIPT_TIMEOUT} секунд."
        )

        return {

            "status":
                "error",

            "error_type":
                "TimeoutExpired",

            "message":
                f"Script exceeded "
                f"{SCRIPT_TIMEOUT} seconds."
        }

    except Exception as e:

        log_error(
            f"{type(e).__name__}: {e}"
        )

        print(
            traceback.format_exc()
        )

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }


# =========================================================
# MODULE CHECK
# =========================================================

def check_python_module(
    module_name
):

    module_name = str(
        module_name
    ).strip()

    if not module_name:

        return {

            "status":
                "error",

            "message":
                "Module name is empty."
        }

    try:

        root = module_name.split(
            "."
        )[0]

        spec = importlib.util.find_spec(
            root
        )

        if spec is None:

            return {

                "status":
                    "error",

                "installed":
                    False,

                "module":
                    module_name,

                "package":
                    module_to_package(
                        module_name
                    ),

                "message":
                    f"Module "
                    f"{module_name} "
                    f"is not installed."
            }

        return {

            "status":
                "success",

            "installed":
                True,

            "module":
                module_name,

            "origin":
                str(spec.origin)
        }

    except Exception as e:

        return {

            "status":
                "error",

            "installed":
                False,

            "module":
                module_name,

            "message":
                str(e)
        }


# =========================================================
# WEBSITE
# =========================================================

def get_filename_from_url(url):

    filename = re.sub(
        r"https?://",
        "",
        url
    )

    filename = re.sub(
        r"[^\w\-_.]",
        "_",
        filename
    )

    return (
        filename.strip("_")
        + ".json"
    )


def fetch_and_save_website_dom(
    url
):

    if sync_playwright is None:

        return {

            "status":
                "error",

            "error_type":
                "PlaywrightNotInstalled",

            "message":
                "Install Playwright with: "
                "pip install playwright"
        }

    if not url.startswith(
        (
            "http://",
            "https://"
        )
    ):

        url = "https://" + url

    if not os.path.exists(
        BRAVE_PATH
    ):

        return {

            "status":
                "error",

            "error_type":
                "BrowserNotFound",

            "message":
                f"Brave not found: "
                f"{BRAVE_PATH}"
        }

    browser = None

    try:

        log_info(
            f"Открываю сайт: {url}"
        )

        with sync_playwright() as p:

            browser = p.chromium.launch(

                executable_path=
                    BRAVE_PATH,

                headless=True,

                args=[
                    "--disable-http2"
                ]
            )

            context = (
                browser.new_context(

                    user_agent=(
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; "
                        "Win64; x64) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/122.0.0.0 "
                        "Safari/537.36"
                    )
                )
            )

            page = context.new_page()

            page.goto(

                url,

                wait_until=
                    "domcontentloaded",

                timeout=30000
            )

            page.wait_for_timeout(
                1500
            )

            title = page.title()

            text = (
                page.locator(
                    "body"
                ).inner_text()
            )

            filename = (
                get_filename_from_url(
                    url
                )
            )

            filepath = os.path.join(

                SITES_DIR,

                filename
            )

            data = {

                "url":
                    url,

                "title":
                    title,

                "text_content":
                    text,

                "ai_analysis":
                    None
            }

            with open(

                filepath,

                "w",

                encoding="utf-8"

            ) as f:

                json.dump(

                    data,

                    f,

                    ensure_ascii=False,

                    indent=2
                )

            log_success(
                f"Сайт сохранён: "
                f"{filepath}"
            )

            return {

                "status":
                    "success",

                "filename":
                    filename,

                "title":
                    title,

                "path":
                    filepath,

                "text_content_preview":
                    text[:3000]
            }

    except Exception as e:

        log_error(
            f"Ошибка браузера: "
            f"{type(e).__name__}: {e}"
        )

        print(
            traceback.format_exc()
        )

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e),

            "traceback":
                traceback.format_exc()
        }

    finally:

        if browser:

            try:

                browser.close()

            except Exception:

                pass


def list_saved_sites():

    if not os.path.exists(
        SITES_DIR
    ):

        return []

    return sorted(

        filename

        for filename
        in os.listdir(
            SITES_DIR
        )

        if filename.endswith(
            ".json"
        )
    )


def read_site_file(
    filename
):

    filename = os.path.basename(
        filename
    )

    filepath = os.path.join(

        SITES_DIR,

        filename
    )

    if not os.path.exists(
        filepath
    ):

        return {

            "status":
                "error",

            "message":
                "File not found."
        }

    try:

        with open(

            filepath,

            "r",

            encoding="utf-8"

        ) as f:

            data = json.load(f)

        if "text_content" in data:

            data[
                "text_content"
            ] = (
                data[
                    "text_content"
                ][:5000]
            )

        return data

    except Exception as e:

        return {

            "status":
                "error",

            "error_type":
                type(e).__name__,

            "message":
                str(e)
        }


def update_json_with_analysis(
    filename,
    ai_analysis
):

    filename = os.path.basename(
        filename
    )

    filepath = os.path.join(

        SITES_DIR,

        filename
    )

    if not os.path.exists(
        filepath
    ):

        return "File not found."

    try:

        with open(

            filepath,

            "r",

            encoding="utf-8"

        ) as f:

            data = json.load(f)

        data[
            "ai_analysis"
        ] = ai_analysis

        with open(

            filepath,

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(

                data,

                f,

                ensure_ascii=False,

                indent=2
            )

        return "Analysis saved."

    except Exception as e:

        return f"Error: {e}"


# =========================================================
# AI TOOLS
# =========================================================

tools = [

    {
        "type": "function",

        "function": {

            "name":
                "fetch_and_save_website_dom",

            "description":
                "Open a website with a browser, "
                "extract its text and save it as JSON.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "url": {

                        "type":
                            "string"
                    }
                },

                "required":
                    ["url"]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "list_saved_sites",

            "description":
                "List saved websites.",

            "parameters": {

                "type":
                    "object",

                "properties": {}
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "read_site_file",

            "description":
                "Read a saved website JSON file.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "filename": {

                        "type":
                            "string"
                    }
                },

                "required":
                    ["filename"]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "update_json_with_analysis",

            "description":
                "Save an AI analysis into a website JSON file.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "filename": {

                        "type":
                            "string"
                    },

                    "ai_analysis": {

                        "type":
                            "string"
                    }
                },

                "required": [
                    "filename",
                    "ai_analysis"
                ]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "execute_python_code",

            "description":
                "Execute Python code.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "code": {

                        "type":
                            "string"
                    }
                },

                "required":
                    ["code"]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "install_python_package",

            "description":
                "Install a Python package using the current Python interpreter.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "package_name": {

                        "type":
                            "string"
                    }
                },

                "required":
                    ["package_name"]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "check_python_module",

            "description":
                "Check whether a Python module is installed.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "module_name": {

                        "type":
                            "string"
                    }
                },

                "required":
                    ["module_name"]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "read_python_script",

            "description":
                "Read the complete source code of an existing Python script.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "script_name": {

                        "type":
                            "string"
                    }
                },

                "required":
                    ["script_name"]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "save_python_script",

            "description":
                "Create and save a new Python script.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "script_name": {

                        "type":
                            "string"
                    },

                    "code": {

                        "type":
                            "string"
                    },

                    "description": {

                        "type":
                            "string"
                    }
                },

                "required": [
                    "script_name",
                    "code"
                ]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "update_python_script",

            "description":
                "Replace the source code of an existing Python script with corrected code.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "script_name": {

                        "type":
                            "string"
                    },

                    "code": {

                        "type":
                            "string"
                    }
                },

                "required": [
                    "script_name",
                    "code"
                ]
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "list_saved_scripts",

            "description":
                "List saved Python scripts.",

            "parameters": {

                "type":
                    "object",

                "properties": {}
            }
        }
    },

    {
        "type": "function",

        "function": {

            "name":
                "run_saved_script",

            "description":
                "Run a saved Python script. If it fails, inspect the error and repair the script.",

            "parameters": {

                "type":
                    "object",

                "properties": {

                    "script_name": {

                        "type":
                            "string"
                    },

                    "args": {

                        "type":
                            "array",

                        "items": {

                            "type":
                                "string"
                        }
                    }
                },

                "required":
                    ["script_name"]
            }
        }
    }
]


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = {

    "role":
        "system",

    "content":
"""
You are a Python AI Agent with automatic self-healing.

LANGUAGE:

Always answer in the same language as the user.

=========================================================
PUBLIC AI STATUS
=========================================================

Before using tools, when useful, briefly state what you are
about to do.

Keep it short.

Example:

"Проверяю скрипт и сначала посмотрю traceback."

"Сначала читаю текущий код, затем исправлю ошибку."

"Проверяю отсутствующие зависимости."

IMPORTANT:

Do NOT output hidden chain-of-thought.

Do NOT expose private internal reasoning.

Only provide a short useful summary of the current action,
diagnosis, or plan.

=========================================================
CAPABILITIES
=========================================================

You can:

- create Python scripts;
- save Python scripts;
- read Python scripts;
- update existing Python scripts;
- run Python scripts;
- install Python dependencies;
- check Python modules;
- execute Python code;
- work with websites;
- read saved websites;
- maintain chat history.

=========================================================
SCRIPT CREATION
=========================================================

If the user asks to create or save a Python script,
use save_python_script.

Before saving code, make sure it is syntactically valid.

=========================================================
SCRIPT EXECUTION
=========================================================

If the user asks to run a saved script,
use run_saved_script.

Never claim that a program works if returncode != 0.

=========================================================
DEPENDENCIES
=========================================================

If a required Python module is missing,
use install_python_package.

Do not tell the user to install a dependency manually
if you can install it using the tool.

=========================================================
AUTOMATIC SELF-HEALING
=========================================================

When a saved Python script returns status="error":

1. Read the existing script using read_python_script.

2. Inspect:
   - source code;
   - error_type;
   - stderr;
   - traceback;
   - returncode.

3. Identify the actual cause.

4. Fix the existing code while preserving its purpose.

5. Update the existing script using update_python_script.

6. Run the script again using run_saved_script.

7. If it fails again, repeat.

8. Continue until:
   - the script succeeds; OR
   - the tool-step limit is reached.

Do not merely explain an error when it can be fixed.

Do not hide errors by removing functionality.

Do not replace real functionality with dummy code just to make
the program return code 0.

Do not claim success until run_saved_script returns:

status="success"

=========================================================
CODE REPAIR RULES
=========================================================

When fixing a script:

- preserve the original purpose;
- preserve command-line arguments;
- preserve existing functionality;
- make the smallest reasonable correction;
- do not randomly rewrite unrelated parts;
- do not remove features just because they cause an error;
- verify syntax before saving;
- run the repaired script after saving.

If the error is caused by a missing dependency,
prefer installing the dependency.

If the error is caused by incorrect Python code,
repair the code.

If the error is caused by a missing file, argument, environment
variable, permission, network resource, or external service,
diagnose the actual cause and explain it if it cannot be safely
fixed automatically.

=========================================================
IMPORTANT
=========================================================

A successful save is NOT the same as successful execution.

A successful syntax check is NOT the same as successful execution.

Only successful execution means the task is complete.

Do not call the same tool repeatedly with identical arguments.

Be concise but useful.
"""
}


# =========================================================
# TOOL DISPATCH
# =========================================================

def dispatch_tool(
    name,
    args
):

    if name == "fetch_and_save_website_dom":

        return fetch_and_save_website_dom(
            args.get(
                "url",
                ""
            )
        )

    if name == "list_saved_sites":

        return list_saved_sites()

    if name == "read_site_file":

        return read_site_file(
            args.get(
                "filename",
                ""
            )
        )

    if name == "update_json_with_analysis":

        return update_json_with_analysis(

            args.get(
                "filename",
                ""
            ),

            args.get(
                "ai_analysis",
                ""
            )
        )

    if name == "execute_python_code":

        return execute_python_code(
            args.get(
                "code",
                ""
            )
        )

    if name == "install_python_package":

        return install_python_package(
            args.get(
                "package_name",
                ""
            )
        )

    if name == "check_python_module":

        return check_python_module(
            args.get(
                "module_name",
                ""
            )
        )

    if name == "read_python_script":

        return read_python_script(
            args.get(
                "script_name",
                ""
            )
        )

    if name == "save_python_script":

        return save_python_script(

            args.get(
                "script_name",
                ""
            ),

            args.get(
                "code",
                ""
            ),

            args.get(
                "description",
                ""
            )
        )

    if name == "update_python_script":

        return update_python_script(

            args.get(
                "script_name",
                ""
            ),

            args.get(
                "code",
                ""
            )
        )

    if name == "list_saved_scripts":

        return list_saved_scripts()

    if name == "run_saved_script":

        return run_saved_script(

            args.get(
                "script_name",
                ""
            ),

            args.get(
                "args",
                []
            )
        )

    return {

        "status":
            "error",

        "error_type":
            "UnknownTool",

        "message":
            name
    }


# =========================================================
# CHAT HISTORY
# =========================================================

def save_chat_history(
    filepath,
    history
):

    try:

        with open(

            filepath,

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(

                history,

                f,

                ensure_ascii=False,

                indent=2
            )

    except Exception as e:

        log_error(
            f"Ошибка сохранения чата: "
            f"{e}"
        )


def load_chat_history(
    filepath
):

    try:

        with open(

            filepath,

            "r",

            encoding="utf-8"

        ) as f:

            history = json.load(f)

        if not history:

            return [
                SYSTEM_PROMPT
            ]

        if (
            history[0].get(
                "role"
            )
            == "system"
        ):

            history[0] = (
                SYSTEM_PROMPT
            )

        else:

            history.insert(
                0,
                SYSTEM_PROMPT
            )

        return history

    except Exception as e:

        log_warning(
            f"Не удалось загрузить историю: "
            f"{e}"
        )

        return [
            SYSTEM_PROMPT
        ]


# =========================================================
# PRINT TOOL RESULT
# =========================================================

def print_tool_result(
    name,
    result
):

    print()

    if isinstance(
        result,
        dict
    ):

        status = result.get(
            "status"
        )

        if status == "success":

            log_success(
                f"Инструмент {name} "
                f"завершился успешно."
            )

        elif status == "error":

            log_error(
                f"Инструмент {name} "
                f"вернул ошибку."
            )

        else:

            log_info(
                f"Результат инструмента "
                f"{name}:"
            )

    else:

        log_info(
            f"Результат инструмента "
            f"{name}:"
        )

    try:

        text_result = pretty_json(
            result
        )

    except Exception:

        text_result = str(
            result
        )

    print(
        color(
            truncate_text(
                text_result,
                8000
            ),
            WHITE
        )
    )

    print()


# =========================================================
# AI ERROR
# =========================================================

def print_ai_exception(
    e
):

    log_error(
        f"{type(e).__name__}: {e}"
    )

    print()

    print(
        color(
            "--- FULL TRACEBACK ---",
            RED
        )
    )

    print(
        traceback.format_exc()
    )

    print()

    # Дополнительная диагностика для сетевых ошибок.

    error_text = str(e)

    if (
        "10061"
        in error_text
        or "Connection refused"
        in error_text
        or "ConnectError"
        in error_text
        or "UnsupportedProtocol"
        in error_text
    ):

        print(
            color(
                "--- API DIAGNOSTICS ---",
                YELLOW
            )
        )

        print(
            f"LOCAL_API_URL = "
            f"{LOCAL_API_URL}"
        )

        print(
            f"MODEL_NAME = "
            f"{MODEL_NAME}"
        )

        print(
            "Проверь, что локальный "
            "OpenAI-compatible сервер запущен."
        )

        print()


# =========================================================
# AI PROCESSOR
# =========================================================

def process_chat_message(

    user_text,

    history,

    chat_filepath

):

    if client is None:

        log_error(
            "OpenAI client недоступен."
        )

        print(
            "Установи пакет:"
        )

        print(
            "python -m pip install -U openai"
        )

        return

    # -----------------------------------------------------
    # USER MESSAGE
    # -----------------------------------------------------

    history.append({

        "role":
            "user",

        "content":
            user_text
    })

    executed_tools = set()

    try:

        for step in range(
            MAX_TOOL_STEPS
        ):

            log_step(
                step + 1,
                MAX_TOOL_STEPS
            )

            # -------------------------------------------------
            # AI REQUEST
            # -------------------------------------------------

            log_ai(
                "Отправляю запрос локальной модели..."
            )

            try:

                response = (
                    client.chat.completions.create(

                        model=
                            MODEL_NAME,

                        messages=
                            history,

                        tools=
                            tools,

                        tool_choice=
                            "auto",

                        temperature=
                            0.2
                    )
                )

            except Exception as api_error:

                log_error(
                    "Ошибка при запросе к AI API."
                )

                print_ai_exception(
                    api_error
                )

                error_text = (
                    "AI API ERROR\n\n"
                    + str(api_error)
                    + "\n\n"
                    + traceback.format_exc()
                )

                history.append({

                    "role":
                        "assistant",

                    "content":
                        error_text
                })

                save_chat_history(
                    chat_filepath,
                    history
                )

                return

            # -------------------------------------------------
            # RESPONSE MESSAGE
            # -------------------------------------------------

            try:

                message = (
                    response
                    .choices[0]
                    .message
                )

            except Exception as e:

                log_error(
                    "AI вернул неожиданный ответ."
                )

                print(
                    traceback.format_exc()
                )

                return

            # -------------------------------------------------
            # PUBLIC AI STATUS
            # -------------------------------------------------

            if (
                message.content
                and not message.tool_calls
            ):

                answer = (
                    message.content
                    or ""
                )

                history.append({

                    "role":
                        "assistant",

                    "content":
                        answer
                })

                save_chat_history(

                    chat_filepath,

                    history
                )

                print()

                print(
                    color(
                        "AI:",
                        GREEN
                    )
                )

                print(
                    answer
                )

                print()

                return

            # -------------------------------------------------
            # TOOL CALLS
            # -------------------------------------------------

            if message.tool_calls:

                log_ai(
                    f"Модель решила выполнить "
                    f"{len(message.tool_calls)} "
                    f"действий."
                )

            # -------------------------------------------------
            # SAVE ASSISTANT TOOL CALL MESSAGE
            # -------------------------------------------------

            tool_calls = []

            for tc in message.tool_calls:

                try:

                    tool_calls.append(
                        tc.model_dump()
                    )

                except Exception:

                    tool_calls.append({

                        "id":
                            tc.id,

                        "type":
                            "function",

                        "function": {

                            "name":
                                tc.function.name,

                            "arguments":
                                tc.function.arguments
                        }
                    })

            assistant_message = {

                "role":
                    "assistant",

                "content":
                    message.content
                    or "",

                "tool_calls":
                    tool_calls
            }

            history.append(
                assistant_message
            )

            # -------------------------------------------------
            # PROCESS TOOL CALLS
            # -------------------------------------------------

            for tool_call in (
                message.tool_calls
            ):

                name = (
                    tool_call
                    .function
                    .name
                )

                raw_args = (
                    tool_call
                    .function
                    .arguments
                    or "{}"
                )

                # ---------------------------------------------
                # PARSE ARGUMENTS
                # ---------------------------------------------

                try:

                    args = json.loads(
                        raw_args
                    )

                except Exception as e:

                    log_error(
                        f"Некорректные аргументы "
                        f"инструмента {name}: "
                        f"{e}"
                    )

                    result = {

                        "status":
                            "error",

                        "error_type":
                            "InvalidToolArguments",

                        "message":
                            str(e),

                        "raw_arguments":
                            raw_args
                    }

                    history.append({

                        "role":
                            "tool",

                        "tool_call_id":
                            tool_call.id,

                        "content":
                            json.dumps(

                                result,

                                ensure_ascii=False
                            )
                    })

                    print_tool_result(
                        name,
                        result
                    )

                    continue

                # ---------------------------------------------
                # PUBLIC TOOL STATUS
                # ---------------------------------------------

                log_tool(
                    name
                )

                if args:

                    print(
                        color(
                            "Arguments:",
                            BLUE
                        )
                    )

                    print(
                        pretty_json(
                            args
                        )
                    )

                # ---------------------------------------------
                # DUPLICATE PROTECTION
                # ---------------------------------------------

                tool_key = (

                    name,

                    json.dumps(

                        args,

                        ensure_ascii=False,

                        sort_keys=True
                    )
                )

                if tool_key in executed_tools:

                    result = {

                        "status":
                            "error",

                        "error_type":
                            "DuplicateToolCall",

                        "message":
                            "This exact tool call "
                            "was already executed."
                    }

                    log_warning(
                        "Повторный идентичный "
                        "tool call заблокирован."
                    )

                else:

                    executed_tools.add(
                        tool_key
                    )

                    # -----------------------------------------
                    # EXECUTE TOOL
                    # -----------------------------------------

                    try:

                        result = dispatch_tool(

                            name,

                            args
                        )

                    except Exception as e:

                        log_error(
                            f"Исключение внутри "
                            f"tool {name}: "
                            f"{type(e).__name__}: {e}"
                        )

                        print(
                            traceback.format_exc()
                        )

                        result = {

                            "status":
                                "error",

                            "error_type":
                                type(e).__name__,

                            "message":
                                str(e),

                            "traceback":
                                traceback.format_exc()
                        }

                # ---------------------------------------------
                # SHOW TOOL RESULT
                # ---------------------------------------------

                print_tool_result(
                    name,
                    result
                )

                # ---------------------------------------------
                # RETURN RESULT TO MODEL
                # ---------------------------------------------

                try:

                    result_text = (
                        json.dumps(

                            result,

                            ensure_ascii=False
                        )
                    )

                except Exception:

                    result_text = str(
                        result
                    )

                history.append({

                    "role":
                        "tool",

                    "tool_call_id":
                        tool_call.id,

                    "content":
                        result_text
                })

                save_chat_history(

                    chat_filepath,

                    history
                )

            # -------------------------------------------------
            # CONTINUE MODEL LOOP
            # -------------------------------------------------

            log_ai(
                "Результаты действий переданы модели. "
                "Продолжаю."
            )

        # -----------------------------------------------------
        # MAX STEPS
        # -----------------------------------------------------

        log_warning(
            "Достигнут максимальный лимит "
            f"{MAX_TOOL_STEPS} шагов."
        )

        history.append({

            "role":
                "assistant",

            "content":
                "Достигнут максимальный "
                "лимит шагов агента."
        })

        save_chat_history(

            chat_filepath,

            history
        )

    except Exception as e:

        print_ai_exception(
            e
        )

        error = (

            "AI ERROR:\n\n"

            + str(e)

            + "\n\n"

            + traceback.format_exc()
        )

        history.append({

            "role":
                "assistant",

            "content":
                error
        })

        save_chat_history(

            chat_filepath,

            history
        )


# =========================================================
# BANNER
# =========================================================

def print_banner():

    print()

    print(
        color(
            "=" * 65,
            CYAN
        )
    )

    print(
        color(
            "                    PYTHON AI AGENT",
            MAGENTA
        )
    )

    print(
        color(
            "=" * 65,
            CYAN
        )
    )

    print(
        f"Python : {sys.executable}"
    )

    print(
        f"Model  : {MODEL_NAME}"
    )

    print(
        f"API    : {LOCAL_API_URL}"
    )

    print(
        f"Scripts: {SCRIPTS_DIR}"
    )

    print(
        f"Sites  : {SITES_DIR}"
    )

    print(
        f"Chats  : {CHATS_DIR}"
    )

    print(
        f"Fixes  : {MAX_AUTO_FIX_ATTEMPTS}"
    )

    print(
        color(
            "=" * 65,
            CYAN
        )
    )

    print()

    print(
        "Commands:"
    )

    print(
        "  /help       Show commands"
    )

    print(
        "  /new        Start a new chat"
    )

    print(
        "  /load       Load a chat"
    )

    print(
        "  /chats      List saved chats"
    )

    print(
        "  /scripts    List saved scripts"
    )

    print(
        "  /sites      List saved sites"
    )

    print(
        "  /clear      Clear current chat"
    )

    print(
        "  /api        Check local AI server"
    )

    print(
        "  /config     Show AI configuration"
    )

    print(
        "  /exit       Exit"
    )

    print()


# =========================================================
# HELP
# =========================================================

def print_help():

    print(
        """
Commands:

  /help
      Show this help.

  /new
      Start a new chat.

  /load
      Load a saved chat.

  /chats
      List saved chats.

  /scripts
      List saved Python scripts.

  /sites
      List saved websites.

  /clear
      Clear current conversation.

  /api
      Check connection to the local AI server.

  /config
      Show current model/API configuration.

  /exit
      Exit the program.

Examples:

  Create a Python calculator and save it as calculator.py

  Run calculator.py with arguments 10 20

  Install requests

  Check if numpy is installed

  Open example.com and save its contents

  Создай Python скрипт для калькулятора

  Запусти calculator.py с аргументом 100

  Исправь ошибку в calculator.py
"""
    )


# =========================================================
# CONFIG COMMAND
# =========================================================

def print_config():

    print()

    print(
        color(
            "AI CONFIGURATION",
            CYAN
        )
    )

    print(
        f"LOCAL_API_URL = "
        f"{LOCAL_API_URL}"
    )

    print(
        f"MODEL_NAME = "
        f"{MODEL_NAME}"
    )

    print(
        f"Python = "
        f"{sys.executable}"
    )

    print(
        f"OpenAI package = "
        f"{'installed' if OpenAI is not None else 'NOT INSTALLED'}"
    )

    print(
        f"Client = "
        f"{'created' if client is not None else 'NOT CREATED'}"
    )

    print()


# =========================================================
# CHAT SELECTOR
# =========================================================

def choose_chat():

    files = sorted(

        f

        for f
        in os.listdir(
            CHATS_DIR
        )

        if f.endswith(
            ".json"
        )
    )

    if not files:

        print(
            "No saved chats."
        )

        return None

    print(
        "\nSaved chats:"
    )

    for index, filename in enumerate(

        files,

        1
    ):

        print(
            f"  {index}. "
            f"{filename}"
        )

    value = input(
        "\nSelect chat number: "
    ).strip()

    try:

        index = int(
            value
        ) - 1

        if (
            index < 0
            or index >= len(files)
        ):

            return None

        return os.path.join(

            CHATS_DIR,

            files[index]
        )

    except ValueError:

        return None


# =========================================================
# NEW CHAT
# =========================================================

def new_chat():

    name = input(
        "Chat name: "
    ).strip()

    if not name:

        name = "default_chat"

    safe = re.sub(

        r"[^\w\-]",

        "_",

        name
    )

    filepath = os.path.join(

        CHATS_DIR,

        safe + ".json"
    )

    history = [

        SYSTEM_PROMPT
    ]

    save_chat_history(

        filepath,

        history
    )

    return filepath, history


# =========================================================
# MAIN
# =========================================================

def main():

    print_banner()

    # -----------------------------------------------------
    # DEPENDENCY CHECK
    # -----------------------------------------------------

    if client is None:

        log_warning(
            "OpenAI client недоступен."
        )

        print(
            "Установи:"
        )

        print(
            "python -m pip install -U openai"
        )

        print()

    # -----------------------------------------------------
    # API CHECK
    # -----------------------------------------------------

    check_api_connection()

    print()

    # -----------------------------------------------------
    # DEFAULT CHAT
    # -----------------------------------------------------

    chat_file = os.path.join(

        CHATS_DIR,

        "default_chat.json"
    )

    if os.path.exists(
        chat_file
    ):

        history = load_chat_history(
            chat_file
        )

    else:

        history = [

            SYSTEM_PROMPT
        ]

        save_chat_history(

            chat_file,

            history
        )

    print(
        f"Current chat: "
        f"{os.path.basename(chat_file)}"
    )

    # -----------------------------------------------------
    # CONSOLE LOOP
    # -----------------------------------------------------

    while True:

        try:

            user_text = input(
                "\nYou: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError
        ):

            print(
                "\nGoodbye!"
            )

            break

        if not user_text:

            continue

        command = (
            user_text.lower()
        )

        # -------------------------------------------------
        # EXIT
        # -------------------------------------------------

        if command in (

            "/exit",
            "/quit",
            "exit",
            "quit"

        ):

            print(
                "Goodbye!"
            )

            break

        # -------------------------------------------------
        # HELP
        # -------------------------------------------------

        if command == "/help":

            print_help()

            continue

        # -------------------------------------------------
        # API
        # -------------------------------------------------

        if command == "/api":

            check_api_connection()

            continue

        # -------------------------------------------------
        # CONFIG
        # -------------------------------------------------

        if command == "/config":

            print_config()

            continue

        # -------------------------------------------------
        # NEW
        # -------------------------------------------------

        if command == "/new":

            chat_file, history = (
                new_chat()
            )

            print(

                f"New chat: "
                f"{os.path.basename(chat_file)}"
            )

            continue

        # -------------------------------------------------
        # LOAD
        # -------------------------------------------------

        if command == "/load":

            selected = choose_chat()

            if selected:

                chat_file = selected

                history = (
                    load_chat_history(
                        chat_file
                    )
                )

                print(

                    f"Loaded: "
                    f"{os.path.basename(chat_file)}"
                )

            continue

        # -------------------------------------------------
        # CHATS
        # -------------------------------------------------

        if command == "/chats":

            files = sorted(

                f

                for f
                in os.listdir(
                    CHATS_DIR
                )

                if f.endswith(
                    ".json"
                )
            )

            if not files:

                print(
                    "No chats."
                )

            else:

                for filename in files:

                    print(
                        f"  {filename}"
                    )

            continue

        # -------------------------------------------------
        # SCRIPTS
        # -------------------------------------------------

        if command == "/scripts":

            scripts = (
                list_saved_scripts()
            )

            if not scripts:

                print(
                    "No saved scripts."
                )

            else:

                for filename in scripts:

                    print(
                        f"  {filename}"
                    )

            continue

        # -------------------------------------------------
        # SITES
        # -------------------------------------------------

        if command == "/sites":

            sites = (
                list_saved_sites()
            )

            if not sites:

                print(
                    "No saved sites."
                )

            else:

                for filename in sites:

                    print(
                        f"  {filename}"
                    )

            continue

        # -------------------------------------------------
        # CLEAR
        # -------------------------------------------------

        if command == "/clear":

            history = [

                SYSTEM_PROMPT
            ]

            save_chat_history(

                chat_file,

                history
            )

            print(
                "Chat cleared."
            )

            continue

        # -------------------------------------------------
        # AI
        # -------------------------------------------------

        process_chat_message(

            user_text,

            history,

            chat_file
        )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n\nStopped by user."
        )

    except Exception as e:

        print()

        log_error(
            "FATAL ERROR"
        )

        print(
            traceback.format_exc()
        )

        input(
            "\nPress Enter to exit..."
        )