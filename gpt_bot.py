python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import json
import time
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
import os
import re
import hashlib
import shutil
from datetime import datetime

class FirebaseStorage:
    def __init__(self, user_id, credentials_file="firebase-credentials.json"):
        self.user_id = user_id
       
        if not Path(credentials_file).exists():
            print(f"Файл {credentials_file} не найден - работа выполняется вне Firebase.")
            self.enabled = False
            return
       
        self.enabled = True
        if not firebase_admin._apps:
            try:
                cred = credentials.Certificate(credentials_file)
                firebase_admin.initialize_app(cred)
                print("Firebase инициализирован")
            except Exception as e:
                print(f"ВНИМАНИЕ - ошибка Firebase: {e}")
                self.enabled = False
                return
       
        self.db = firestore.client()
        self.collection = self.db.collection("language_models")
        self.firestore = firestore
   
    def save(self, conversation_history):
        if not self.enabled:
            return
        try:
            doc_ref = self.collection.document(self.user_id)
            doc_ref.set({
                'conversation_history': conversation_history,
                'last_updated': self.firestore.SERVER_TIMESTAMP,
                'version': str(time.time())
            })
            print(f"Сохранено в Firebase: {len(conversation_history)} сообщений")
        except Exception as e:
            print(f"ВНИМАНИЕ - ошибка сохранения в Firebase: {e}")
   
    def load(self):
        if not self.enabled:
            return []
        try:
            doc_ref = self.collection.document(self.user_id)
            doc = doc_ref.get()
            if not doc.exists:
                return []
            data = doc.to_dict()
            return data.get('conversation_history', [])
        except Exception as e:
            print(f"ВНИМАНИЕ - ошибка загрузки из Firebase: {e}")
            return []

class LocalStorage:
    def __init__(self, folder="my_saves"):
        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=True)
        self.memory_file = self.folder / "memory.json"
   
    def save(self, conversation_history):
        try:
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(conversation_history, f, ensure_ascii=False, indent=2)
            print(f"Сохранено локально: {len(conversation_history)} сообщений")
        except Exception as e:
            print(f"ВНИМАНИЕ - ошибка локального сохранения: {e}")
   
    def load(self):
        if not self.memory_file.exists():
            return []
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

class CodeManager:
    def __init__(self, project_folder="."):
        self.project_folder = Path(project_folder)
        self.requests_folder = self.project_folder / "code_requests"
        self.backup_folder = self.project_folder / "code_backups"
       
        self.requests_folder.mkdir(exist_ok=True)
        self.backup_folder.mkdir(exist_ok=True)
       
        self.requests_file = self.requests_folder / "pending_requests.json"
        self._init_files()
   
    def _init_files(self):
        if not self.requests_file.exists():
            with open(self.requests_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
   
    def _create_backup(self, filename):
        filepath = self.project_folder / filename
        if filepath.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{filename}.{timestamp}.backup"
            backup_path = self.backup_folder / backup_name
            shutil.copy2(filepath, backup_path)
            return backup_name
        return None
   
    def create_change_request(self, filename, proposed_code, description, reason=""):
        if not filename.endswith('.py'):
            return {'success': False, 'error': 'Редактированию подлежат только файлы с расширение .py'}
       
        filepath = self.project_folder / filename
        original_code = ""
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                original_code = f.read()
       
        backup = self._create_backup(filename)
       
        request_id = hashlib.md5(f"{filename}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
       
        request = {
            'id': request_id,
            'filename': filename,
            'original_code': original_code,
            'proposed_code': proposed_code,
            'description': description,
            'reason': reason,
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
            'backup': backup
        }
       
        with open(self.requests_file, 'r', encoding='utf-8') as f:
            requests = json.load(f)
       
        requests.append(request)
       
        with open(self.requests_file, 'w', encoding='utf-8') as f:
            json.dump(requests, f, ensure_ascii=False, indent=2)
       
        return {'success': True, 'request_id': request_id, 'message': f'Запрос #{request_id} создан. Ожидает подтверждения.'}
   
    def get_pending_requests(self):
        with open(self.requests_file, 'r', encoding='utf-8') as f:
            requests = json.load(f)
        return [r for r in requests if r['status'] == 'pending']
   
    def approve_request(self, request_id):
        with open(self.requests_file, 'r', encoding='utf-8') as f:
            requests = json.load(f)
       
        for i, req in enumerate(requests):
            if req['id'] == request_id and req['status'] == 'pending':
                filepath = self.project_folder / req['filename']
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(req['proposed_code'])
               
                req['status'] = 'approved'
                req['approved_at'] = datetime.now().isoformat()
               
                with open(self.requests_file, 'w', encoding='utf-8') as f:
                    json.dump(requests, f, ensure_ascii=False, indent=2)
               
                return {'success': True, 'message': f'Запрос #{request_id} одобрен. Изменения применены.'}
       
        return {'success': False, 'error': f'Запрос #{request_id} не найден'}
   
    def reject_request(self, request_id):
        with open(self.requests_file, 'r', encoding='utf-8') as f:
            requests = json.load(f)
       
        for i, req in enumerate(requests):
            if req['id'] == request_id and req['status'] == 'pending':
                req['status'] = 'rejected'
                req['rejected_at'] = datetime.now().isoformat()
               
                with open(self.requests_file, 'w', encoding='utf-8') as f:
                    json.dump(requests, f, ensure_ascii=False, indent=2)
               
                return {'success': True, 'message': f'Запрос #{request_id} отклонен.'}
       
        return {'success': False, 'error': f'Запрос #{request_id} не найден'}
   
    def show_diff(self, request_id):
        with open(self.requests_file, 'r', encoding='utf-8') as f:
            requests = json.load(f)
       
        for req in requests:
            if req['id'] == request_id:
                original_lines = req['original_code'].split('\n')
                proposed_lines = req['proposed_code'].split('\n')
               
                diff = []
                for i, line in enumerate(proposed_lines):
                    if i < len(original_lines):
                        if line != original_lines[i]:
                            diff.append(f"  {i+1}: - {original_lines[i]}")
                            diff.append(f"  {i+1}: + {line}")
                    else:
                        diff.append(f"  {i+1}: + {line}")
               
                for i in range(len(proposed_lines), len(original_lines)):
                    diff.append(f"  {i+1}: - {original_lines[i]}")
               
                return '\n'.join(diff) if diff else "Нет изменений"
       
        return "Запрос не найден"

class GPTDialogueBot:
    def __init__(self, model_name="sberbank-ai/rugpt3small_based_on_gpt2", use_cloud=True, user_id="user"):
        self.user_id = user_id
        self.use_cloud = use_cloud
        self.conversation_history = []
        self.code_manager = CodeManager()
       
        print("=" * 60)
        print("ЗАПУСК НЕЙРОСЕТИ")
        print("=" * 60)
        print("Загрузка языковой модели...")
        print("Первая активация может занять некоторое время.")
       
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForCausalLM.from_pretrained(model_name)
            print("Модель загружена")
        except Exception as e:
            print(f"ВНИМАНИЕ - ошибка загрузки модели: {e}")
            raise
       
        self.local_storage = LocalStorage()
       
        if use_cloud:
            self.cloud_storage = FirebaseStorage(user_id)
        else:
            self.cloud_storage = None
       
        self._load_history()
        self._load_seed_description()
   
    def _load_seed_description(self):
        seed_file = Path("seed_description.txt")
        if seed_file.exists():
            with open(seed_file, 'r', encoding='utf-8') as f:
                text = f.read()
            print(f"Найден слепок: {len(text)} символов")
            self._process_seed_text(text)
   
    def _process_seed_text(self, text):
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
       
        print(f"Обработка слепка: {len(sentences)} предложений")
       
        for i, sentence in enumerate(sentences[:20]):
            questions = []
            if 'зовут' in sentence or 'имя' in sentence:
                questions.append('Как тебя зовут?')
            if 'характер' in sentence:
                questions.append('Какой у тебя характер?')
            if 'умею' in sentence or 'могу' in sentence:
                questions.append('Что ты умеешь?')
            if 'правило' in sentence:
                questions.append('Какие у тебя правила?')
           
            questions.append('Расскажи о себе')
            questions.append(f'Что ты знаешь о {sentence[:30]}?')
           
            for q in questions[:3]:
                self.learn_from_feedback(q, sentence, 5)
           
            if (i + 1) % 5 == 0:
                print(f"   Обработано {i+1}/{len(sentences)} предложений")
       
        self._save_history()
        print("Слепок загружен")
   
    def _load_history(self):
        history = []
       
        if self.cloud_storage:
            try:
                history = self.cloud_storage.load()
                if history:
                    print(f"Загружено из облака: {len(history)} сообщений")
            except:
                pass
       
        if not history:
            history = self.local_storage.load()
            if history:
                print(f"Загружено локально: {len(history)} сообщений")
       
        if history:
            self.conversation_history = history
   
    def _save_history(self):
        self.local_storage.save(self.conversation_history)
       
        if self.cloud_storage:
            try:
                self.cloud_storage.save(self.conversation_history)
            except:
                pass
   
    def generate_response(self, user_input):
        history_text = ""
        for msg in self.conversation_history[-10:]:
            history_text += f"Пользователь: {msg['user']}\nБот: {msg['bot']}\n"
       
        prompt = history_text + f"Пользователь: {user_input}\nБот:"
        inputs = self.tokenizer.encode(prompt, return_tensors='pt')
        
        attention_mask = torch.ones_like(inputs)
       
        with torch.no_grad():
            outputs = self.model.generate(
                inputs,
                attention_mask=attention_mask,
                max_new_tokens=100,
                do_sample=True,
                temperature=0.8,
                top_p=0.9,
                top_k=50,
                repetition_penalty=1.1,
                pad_token_id=self.tokenizer.eos_token_id
            )
       
        full_response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
       
        try:
            response = full_response.split("Бот:")[-1].strip()
        except:
            response = full_response
       
        response = response.replace("\n", " ").strip()
       
        if not response or len(response) < 2:
            response = "Ошибка формулирования ответа - измените свой запрос/задайте его повторно."
       
        if len(response) > 500:
            response = response[:500] + "..."
       
        self.conversation_history.append({
            'user': user_input,
            'bot': response,
            'timestamp': time.time()
        })
       
        if len(self.conversation_history) % 5 == 0:
            self._save_history()
       
        return response
   
    def learn_from_feedback(self, user_input, response, feedback_score):
        for msg in self.conversation_history:
            if msg.get('user') == user_input and msg.get('bot') == response:
                msg['feedback'] = feedback_score
                break
        self._save_history()
        print(f"Оценка {feedback_score} сохранена")
        return 0.0
   
    def read_own_code(self, filename=None):
        if filename:
            filepath = Path(filename)
            if filepath.exists() and filepath.suffix == '.py':
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                return f"Файл {filename}:\n```python\n{content[:2000]}\n```"
            else:
                return f"Файл {filename} не найден или не является Python файлом"
        else:
            files = list(Path('.').glob('*.py'))
            if not files:
                return "Python файлы не найдены"
            result = "Доступные файлы:\n"
            for f in files:
                result += f"- {f.name}\n"
            return result
   
    def suggest_code_improvement(self, filename, description, reason):
        if not Path(filename).exists():
            return f"Файл {filename} не найден"
       
        with open(filename, 'r', encoding='utf-8') as f:
            original_code = f.read()
       
        improved_code = self._generate_code_improvement(original_code, description)
       
        result = self.code_manager.create_change_request(
            filename=filename,
            proposed_code=improved_code,
            description=description,
            reason=reason
        )
       
        return result
   
    def _generate_code_improvement(self, original_code, suggestion):
        suggestion_lower = suggestion.lower()
       
        if "слой" in suggestion_lower or "layer" in suggestion_lower:
            if "добавить" in suggestion_lower:
                lines = original_code.split('\n')
                for i, line in enumerate(lines):
                    if "hidden_sizes" in line or "HIDDEN_SIZES" in line:
                        lines[i] = line.replace(']', ', 1024]')
                        break
                return '\n'.join(lines)
       
        return original_code + f"\n\n# Предложено улучшение: {suggestion}"
   
    def get_statistics(self):
        total = len(self.conversation_history)
        if total == 0:
            return "Нет сообщений"
       
        avg_length = sum(len(msg['bot']) for msg in self.conversation_history) / total
        scored = [msg['feedback'] for msg in self.conversation_history if 'feedback' in msg]
        avg_score = sum(scored) / len(scored) if scored else 0
       
        return f"""СТАТИСТИКА:
├ Всего сообщений: {total}
├ Средняя длина ответа: {avg_length:.0f} символов
├ Средняя оценка: {avg_score:.1f}/5
└ Модель: ruGPT3 (русскоязычная)"""
   
    def get_pending_requests(self):
        return self.code_manager.get_pending_requests()
   
    def approve_request(self, request_id):
        return self.code_manager.approve_request(request_id)
   
    def reject_request(self, request_id):
        return self.code_manager.reject_request(request_id)
   
    def show_diff(self, request_id):
        return self.code_manager.show_diff(request_id)

USER_ID = "my_language_bot"
USE_CLOUD = True

bot = GPTDialogueBot(use_cloud=USE_CLOUD, user_id=USER_ID)
print("Бот готов к запуску.")

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8717016392:AAFv0GBOBl0w9O_mjpJFGTByxSUGJPytZ4o"

ADMIN_ID = None
evaluation_enabled = True

user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    if ADMIN_ID is None:
        ADMIN_ID = update.effective_user.id
        print(f"Администратор установлен: {ADMIN_ID}")
   
    await update.message.reply_text(
        "Языковая модель готова к работе.\n\n"
        "Команды:\n"
        "/stat — статистика\n"
        "/save — сохранить память\n"
        "/code — показать файлы кода\n"
        "/code [имя_файла] — показать содержимое файла\n"
        "/suggest [файл] [описание] [причина] — предложить улучшение\n"
        "/requests — показать ожидающие запросы\n"
        "/show [ID] — показать различия\n"
        "/approve [ID] — одобрить изменение\n"
        "/reject [ID] — отклонить запрос\n"
        "/eval_on — включить режим оценивания\n"
        "/eval_off — выключить режим оценивания\n"
        "/help — помощь",
        parse_mode="Markdown"
    )
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Инструкция по работе:\n\n"
        "1. Отправить запрос\n"
        "2. Дождаться ответа\n"
        "3. Оценить работу от 0 до 5 (если режим оценивания включен)\n\n"
        "Команды:\n"
        "/stat — статистика\n"
        "/save — сохранить память\n"
        "/code — показать файлы кода\n"
        "/code имя_файла — показать содержимое\n"
        "/suggest файл описание причина — предложить улучшение\n"
        "/requests — ожидающие запросы\n"
        "/show ID — показать изменения\n"
        "/approve ID — одобрить\n"
        "/reject ID — отклонить\n"
        "/eval_on — включить оценивание\n"
        "/eval_off — выключить оценивание",
        parse_mode="Markdown"
    )

async def eval_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global evaluation_enabled
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Необходимы права Админестратора")
        return
   
    evaluation_enabled = True
    await update.message.reply_text("Режим оценивания - ВКЛЮЧЕН")

async def eval_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global evaluation_enabled
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Необходимы права Админестратора")
        return
   
    evaluation_enabled = False
    await update.message.reply_text("Режим оценивания - ВЫКЛЮЧЕН")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_input = update.message.text
   
    if user_input.startswith('/'):
        return
   
    if user_id in user_sessions and user_sessions[user_id].get('waiting_for_feedback'):
        await update.message.reply_text("ОШИБКА - необходима оценка предыдущего ответа (0-5)")
        return
   
    response = bot.generate_response(user_input)
   
    await update.message.reply_text(f"{response}")
   
    if evaluation_enabled:
        user_sessions[user_id] = {
            'user_input': user_input,
            'response': response,
            'waiting_for_feedback': True
        }
        await update.message.reply_text("Оцените ответ (0-5):")
    else:
        bot.learn_from_feedback(user_input, response, 5)
        await update.message.reply_text("Режим оценивания отключен - ответ сохранен автоматически")

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
   
    if user_id not in user_sessions:
        await update.message.reply_text("Необходимо получить запрос")
        return
   
    session = user_sessions[user_id]
   
    if not session.get('waiting_for_feedback'):
        await update.message.reply_text("Необходимо получить запрос")
        return
   
    try:
        feedback = int(update.message.text)
        if feedback < 0 or feedback > 5:
            raise ValueError
    except:
        await update.message.reply_text("Введите значение от 0 до 5")
        return
   
    session['waiting_for_feedback'] = False
   
    bot.learn_from_feedback(
        session['user_input'],
        session['response'],
        feedback
    )
   
    await update.message.reply_text(f"Оценка {feedback} сохранена")
   
    del user_sessions[user_id]

async def stat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(bot.get_statistics())

async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot._save_history()
    await update.message.reply_text("Память сохранена")

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        filename = args[0]
        result = bot.read_own_code(filename)
    else:
        result = bot.read_own_code()
    await update.message.reply_text(result[:4000])

async def suggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = ' '.join(context.args).split('"')
    if len(args) >= 3:
        filename = args[0].strip()
        description = args[1].strip()
        reason = args[2].strip() if len(args) > 2 else ""
       
        result = bot.suggest_code_improvement(filename, description, reason)
       
        if isinstance(result, dict):
            if result.get('success'):
                await update.message.reply_text(
                    f"{result['message']}\n"
                    f"ID: {result['request_id']}\n"
                    f"Для просмотра: /show {result['request_id']}\n"
                    f"Для одобрения: /approve {result['request_id']}"
                )
            else:
                await update.message.reply_text(f"{result.get('error', 'Ошибка')}")
        else:
            await update.message.reply_text(result)
    else:
        await update.message.reply_text("Формат: /suggest файл.py \"описание\" \"причина\"")

async def requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requests = bot.get_pending_requests()
    if not requests:
        await update.message.reply_text("Нет ожидающих запросов")
        return
   
    text = "Ожидающие запросы:\n"
    for req in requests:
        text += f"\nID: {req['id']}\nФайл: {req['filename']}\nОписание: {req['description']}\n"
    await update.message.reply_text(text[:4000])

async def show_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите ID запроса: /show ID")
        return
   
    request_id = context.args[0]
    diff = bot.show_diff(request_id)
    await update.message.reply_text(f"Различия:\n{diff[:4000]}")

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Необходимы права Админестратора")
        return
   
    if not context.args:
        await update.message.reply_text("Укажите ID запроса: /approve ID")
        return
   
    request_id = context.args[0]
   
    diff = bot.show_diff(request_id)
    await update.message.reply_text(f"Показываю различия:\n{diff[:2000]}")
    await update.message.reply_text("Применить изменения? (да/нет)")
   
    context.user_data['pending_approve'] = request_id

async def approve_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'pending_approve' not in context.user_data:
        return
   
    if update.message.text.lower() in ['да', 'yes', 'y']:
        request_id = context.user_data.pop('pending_approve')
        result = bot.approve_request(request_id)
        await update.message.reply_text(result['message'])
    else:
        context.user_data.pop('pending_approve')
        await update.message.reply_text("Отменено")

async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Необходимы права Админестратора")
        return
   
    if not context.args:
        await update.message.reply_text("Укажите ID запроса: /reject ID")
        return
   
    request_id = context.args[0]
    result = bot.reject_request(request_id)
    await update.message.reply_text(result['message'])

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
   
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stat", stat_command))
    app.add_handler(CommandHandler("save", save_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("suggest", suggest_command))
    app.add_handler(CommandHandler("requests", requests_command))
    app.add_handler(CommandHandler("show", show_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("reject", reject_command))
    app.add_handler(CommandHandler("eval_on", eval_on_command))
    app.add_handler(CommandHandler("eval_off", eval_off_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, approve_confirm))
   
    print("Нейросеть работает в формате Telegram бота")
    print("Найдите бота в Telegram и отправьте команду - /start")
    app.run_polling()

if __name__ == "__main__":
    main()
