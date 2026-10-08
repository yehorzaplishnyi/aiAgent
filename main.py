import json
import os
import re
import subprocess
import sys
from openai import OpenAI
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------
# КОНФИГУРАЦИЯ И ПАПКИ
# ---------------------------------------------------------

APIKEY = "sXjpYRX2urzUJjLTxad4GdVf9xdZX3"
brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

SITES_DIR = "./saved_sites"
CHATS_DIR = "./chats"
SCRIPTS_DIR = "./saved_scripts"

# Создаем необходимые директории
os.makedirs(SITES_DIR, exist_ok=True)
os.makedirs(CHATS_DIR, exist_ok=True)
os.makedirs(SCRIPTS_DIR, exist_ok=True)

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=APIKEY,
)

# ---------------------------------------------------------
# 1. ФУНКЦИИ-ИНСТРУМЕНТЫ (WEB & FILE SYSTEM)
# ---------------------------------------------------------

def get_filename_from_url(url: str) -> str:
    """Генерация стандартного имени файла из URL"""
    filename = re.sub(r'https?://', '', url)
    return re.sub(r'[^\w\-_.]', '_', filename).strip('_') + ".json"

def fetch_and_save_website_dom(url: str) -> dict:
    """Сбор DOM страницы с помощью Playwright и сохранение в JSON"""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=brave_path,
            headless=True,
            args=['--disable-http2']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"\n[Загрузка сайта {url} через Playwright...]")
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(2000)
            
            title = page.title()
            text = page.locator("body").inner_text()

            filename = get_filename_from_url(url)
            filepath = os.path.join(SITES_DIR, filename)

            data = {
                "url": url,
                "title": title,
                "text_content": text,
                "ai_analysis": None
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            return {
                "status": "success",
                "filename": filename,
                "title": title,
                "text_content_preview": text[:3000]
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            browser.close()

def list_saved_sites() -> list:
    """Возвращает список всех сохраненных сайтов"""
    if not os.path.exists(SITES_DIR):
        return []
    return [f for f in os.listdir(SITES_DIR) if f.endswith('.json')]

def read_site_file(filename: str) -> dict:
    """Считывает содержимое конкретного JSON-файла сайта"""
    filepath = os.path.join(SITES_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "text_content" in data and len(data["text_content"]) > 3000:
                data["text_content"] = data["text_content"][:3000] + "... [содержимое усечено]"
            return data
    return {"error": f"Файл {filename} не найден"}

def update_json_with_analysis(filename: str, ai_analysis: str) -> str:
    """Запись результата анализа в JSON-файл сайта"""
    filepath = os.path.join(SITES_DIR, filename)
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            data["ai_analysis"] = ai_analysis

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            return f"Анализ успешно сохранен в файл {filename}"
        else:
            return f"Файл {filename} не найден"
    except Exception as e:
        return f"Ошибка при сохранении: {e}"

# ---------------------------------------------------------
# 2. ФУНКЦИИ-ИНСТРУМЕНТЫ (CODE, PIP & SCRIPTS PERSISTENCE)
# ---------------------------------------------------------

def execute_python_code(code: str) -> dict:
    """Динамически выполняет Python-код в локальной среде"""
    try:
        process = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "stdout": process.stdout,
            "stderr": process.stderr,
            "returncode": process.returncode
        }
    except subprocess.TimeoutExpired:
        return {"error": "Превышено время ожидания выполнения кода (30 секунд)."}
    except Exception as e:
        return {"error": str(e)}

def install_python_package(package_name: str) -> dict:
    """Динамически устанавливает указанный Python-пакет с помощью pip"""
    clean_name = re.sub(r'[^a-zA-Z0-9\-_>=<.]', '', package_name)
    if not clean_name:
        return {"status": "error", "message": "Некорректное имя пакета."}

    try:
        print(f"\n[Установка пакета: {clean_name}...]")
        process = subprocess.run(
            [sys.executable, "-m", "pip", "install", clean_name],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if process.returncode == 0:
            return {
                "status": "success",
                "message": f"Пакет '{clean_name}' успешно установлен.",
                "stdout": process.stdout
            }
        else:
            return {
                "status": "error",
                "message": f"Ошибка при установке пакета '{clean_name}'.",
                "stderr": process.stderr
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Превышено время ожидания установки (120 секунд)."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def save_python_script(script_name: str, code: str, description: str = "") -> dict:
    """Сохраняет Python-код в файл в папке saved_scripts для последующего переиспользования"""
    if not script_name.endswith(".py"):
        script_name += ".py"
    
    safe_name = re.sub(r'[^\w\-_.]', '_', script_name)
    filepath = os.path.join(SCRIPTS_DIR, safe_name)
    
    try:
        formatted_code = code
        if description:
            formatted_code = f'"""\nОписание: {description}\n"""\n\n' + code

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_code)
            
        return {
            "status": "success",
            "message": f"Скрипт успешно сохранен как '{safe_name}'",
            "script_name": safe_name
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def list_saved_scripts() -> list:
    """Возвращает список всех ранее сохраненных скриптов"""
    if not os.path.exists(SCRIPTS_DIR):
        return []
    
    scripts = []
    for file in os.listdir(SCRIPTS_DIR):
        if file.endswith('.py'):
            filepath = os.path.join(SCRIPTS_DIR, file)
            description = ""
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read(500)
                    match = re.search(r'"""\nОписание:\s*(.*?)\n"""', content, re.DOTALL)
                    if match:
                        description = match.group(1).strip()
            except Exception:
                pass
            scripts.append({"script_name": file, "description": description})
            
    return scripts

def run_saved_script(script_name: str, args: list = None) -> dict:
    """Запускает ранее сохраненный Python-скрипт с передачей аргументов командной строки"""
    if not script_name.endswith(".py"):
        script_name += ".py"
        
    filepath = os.path.join(SCRIPTS_DIR, script_name)
    if not os.path.exists(filepath):
        return {"status": "error", "message": f"Скрипт '{script_name}' не найден."}

    cmd = [sys.executable, filepath]
    if args:
        cmd.extend([str(a) for a in args])

    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "stdout": process.stdout,
            "stderr": process.stderr,
            "returncode": process.returncode
        }
    except subprocess.TimeoutExpired:
        return {"error": "Превышено время ожидания выполнения скрипта (30 секунд)."}
    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------------------------
# 3. ОПИСАНИЕ ИНСТРУМЕНТОВ ДЛЯ ИИ
# ---------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "fetch_and_save_website_dom",
            "description": "Загружает сайт по URL с помощью браузера, собирает его текст и сохраняет в JSON.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Адрес сайта, например https://example.com"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_saved_sites",
            "description": "Получает список всех ранее сохраненных JSON-файлов в папке saved_sites.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_site_file",
            "description": "Читает содержимое конкретного JSON-файла с сайтом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла, например 'example_com.json'"
                    }
                },
                "required": ["filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_json_with_analysis",
            "description": "Сохраняет результат анализа сайта в его JSON-файл.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя файла, например 'example_com.json'"
                    },
                    "ai_analysis": {
                        "type": "string",
                        "description": "Текст анализа"
                    }
                },
                "required": ["filename", "ai_analysis"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Выполняет динамический Python-код и возвращает stdout/stderr. Используется для тестирования и вычислений.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Исходный код на Python для выполнения"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "install_python_package",
            "description": "Устанавливает необходимую Python-библиотеку/пакет через pip, если её нет в системе (например, 'pandas', 'requests').",
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "description": "Имя пакета для установки, например 'pandas' или 'scikit-learn'"
                    }
                },
                "required": ["package_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_python_script",
            "description": "Сохраняет написанный Python-код в папку saved_scripts для повторного использования в будущем.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_name": {
                        "type": "string",
                        "description": "Имя файла скрипта (например, 'data_parser.py')"
                    },
                    "code": {
                        "type": "string",
                        "description": "Полный Python-код скрипта"
                    },
                    "description": {
                        "type": "string",
                        "description": "Краткое описание того, что делает этот скрипт"
                    }
                },
                "required": ["script_name", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_saved_scripts",
            "description": "Возвращает список всех ранее сохраненных Python-скриптов и их описаний.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_saved_script",
            "description": "Запускает ранее сохраненный Python-скрипт по имени из папки saved_scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_name": {
                        "type": "string",
                        "description": "Имя сохраненного скрипта (например, 'data_parser.py')"
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список аргументов командной строки (sys.argv), передаваемых скрипту"
                    }
                },
                "required": ["script_name"]
            }
        }
    }
]

# ---------------------------------------------------------
# 4. СИСТЕМНЫЙ ПРОМПТ И МЕНЕДЖЕР ЧАТОВ
# ---------------------------------------------------------

SYSTEM_PROMPT = {
    "role": "system", 
    "content": "Ты — автономный AI Агент для анализа сайтов и автоматизации задач с помощью Python.\n"
               "У тебя есть следующие инструменты:\n"
               "1. Работа с веб-страницами: `fetch_and_save_website_dom`, `list_saved_sites`, `read_site_file`, `update_json_with_analysis`.\n"
               "2. Исполнение и сохранение кода Python:\n"
               "   - Выполнять динамический код: `execute_python_code`.\n"
               "   - Устанавливать отсутствующие библиотеки: если код возвращает ошибку `ModuleNotFoundError`, используй `install_python_package`.\n"
               "   - Сохранять полезный код на будущее: `save_python_script`.\n"
               "   - Проверять готовые сохраненные скрипты: `list_saved_scripts`.\n"
               "   - Вызывать сохраненные скрипты: `run_saved_script`."
}

def save_chat_history(chat_filepath, conversation_history):
    """Сохраняет историю диалога в файл чата"""
    clean_history = []
    for msg in conversation_history:
        if hasattr(msg, "model_dump"):
            clean_history.append(msg.model_dump())
        else:
            clean_history.append(msg)

    with open(chat_filepath, "w", encoding="utf-8") as f:
        json.dump(clean_history, f, ensure_ascii=False, indent=2)

def select_or_create_chat():
    """Меню выбора или создания чата при запуске"""
    chat_files = [f for f in os.listdir(CHATS_DIR) if f.endswith(".json")]

    print("\n=== ВЫБОР ЧАТА ===")
    if chat_files:
        for idx, file in enumerate(chat_files, 1):
            chat_name = file.replace(".json", "")
            print(f"{idx}. {chat_name}")
    else:
        print("(Сохраненных чатов пока нет)")

    print("0. Создать новый чат")
    print("==================")

    while True:
        choice = input("Выберите номер чата: ").strip()

        if choice == "0":
            chat_name = input("Введите название нового чата: ").strip()
            if not chat_name:
                chat_name = "default_chat"
            safe_name = re.sub(r'[^\w\-_]', '_', chat_name)
            filepath = os.path.join(CHATS_DIR, f"{safe_name}.json")
            history = [SYSTEM_PROMPT]
            save_chat_history(filepath, history)
            print(f"\nСоздан новый чат: '{chat_name}'")
            return filepath, history

        elif choice.isdigit() and 1 <= int(choice) <= len(chat_files):
            selected_file = chat_files[int(choice) - 1]
            filepath = os.path.join(CHATS_DIR, selected_file)
            with open(filepath, "r", encoding="utf-8") as f:
                history = json.load(f)
            print(f"\nЗагружен чат: '{selected_file.replace('.json', '')}'")
            return filepath, history

        else:
            print("Некорректный выбор. Попробуйте еще раз.")

# ---------------------------------------------------------
# 5. ОБРАБОТЧИК ДИАЛОГА (DISPATCHER)
# ---------------------------------------------------------

def process_chat_message(user_input_text, conversation_history, chat_filepath):
    conversation_history.append({"role": "user", "content": user_input_text})

    try:
        response = client.chat.completions.create(
            model="qwen2.5-3b-instruct-q8_0",
            messages=conversation_history,
            tools=tools,
            tool_choice="auto",
            temperature=0.7
        )

        response_message = response.choices[0].message

        if response_message.tool_calls:
            conversation_history.append(response_message)

            for tool_call in response_message.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                print(f"\n[ИИ вызывает инструмент: {func_name} | Аргументы: {args}]")

                # Маршрутизация функций
                if func_name == "fetch_and_save_website_dom":
                    result = fetch_and_save_website_dom(args.get("url"))
                elif func_name == "list_saved_sites":
                    result = list_saved_sites()
                elif func_name == "read_site_file":
                    result = read_site_file(args.get("filename"))
                elif func_name == "update_json_with_analysis":
                    result = update_json_with_analysis(args.get("filename"), args.get("ai_analysis"))
                elif func_name == "execute_python_code":
                    result = execute_python_code(args.get("code"))
                elif func_name == "install_python_package":
                    result = install_python_package(args.get("package_name"))
                elif func_name == "save_python_script":
                    result = save_python_script(
                        args.get("script_name"),
                        args.get("code"),
                        args.get("description", "")
                    )
                elif func_name == "list_saved_scripts":
                    result = list_saved_scripts()
                elif func_name == "run_saved_script":
                    result = run_saved_script(
                        args.get("script_name"),
                        args.get("args")
                    )
                else:
                    result = {"error": "Неизвестный инструмент"}

                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })

            final_response = client.chat.completions.create(
                model="qwen2.5-3b-instruct-q8_0",
                messages=conversation_history
            )

            ai_reply = final_response.choices[0].message.content
            conversation_history.append({"role": "assistant", "content": ai_reply})

            print("\n--- Ответ AI ---")
            print(ai_reply)
            print("----------------\n")

        else:
            ai_reply = response_message.content
            conversation_history.append({"role": "assistant", "content": ai_reply})

            print("\n--- Ответ AI ---")
            print(ai_reply)
            print("----------------\n")

        save_chat_history(chat_filepath, conversation_history)

    except Exception as e:
        print(f"Ошибка при обращении к LLM: {e}")

# ---------------------------------------------------------
# 6. ГЛАВНЫЙ ЦИКЛ ПРОГРАММЫ
# ---------------------------------------------------------

current_chat_file, current_history = select_or_create_chat()

print("\nЧат запущен! Напишите 'exit' для выхода.")

while True:
    user_input = input("\nВы: ").strip()

    if not user_input:
        continue

    if user_input.lower() in ["exit", "quit"]:
        print("Завершение работы...")
        break

    process_chat_message(user_input, current_history, current_chat_file)