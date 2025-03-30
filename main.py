import asyncio
import json
import logging
import base64
import io
import time
import os
import subprocess
import sys
import signal
from typing import Dict, Any, Optional, List

import requests
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler

# Настройка логирования - более компактное и понятное
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%H:%M:%S'
)
# Отключаем логирование от библиотек
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Функция для завершения других экземпляров бота
def kill_other_instances():
    """Завершает все другие запущенные экземпляры бота"""
    try:
        current_pid = os.getpid()
        
        if sys.platform == "win32":
            # Для Windows используем taskkill для принудительного завершения
            try:
                subprocess.call(
                    "taskkill /f /fi \"IMAGENAME eq python.exe\" /fi \"PID ne " + str(current_pid) + "\"",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info("Завершены все другие экземпляры Python")
            except Exception as e:
                logger.warning(f"Ошибка при завершении других экземпляров: {e}")
        else:
            # Для Linux/Unix
            output = subprocess.check_output(["ps", "aux"], text=True)
            for line in output.split('\n'):
                if "python" in line and "main.py" in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pid = int(parts[1])
                            if pid != current_pid:
                                os.kill(pid, signal.SIGKILL)  # SIGKILL вместо SIGTERM
                                logger.info(f"Завершен другой экземпляр бота (PID: {pid})")
                        except Exception as e:
                            pass
    
    except Exception as e:
        logger.warning(f"Не удалось завершить другие экземпляры: {e}")

# Конфигурация API
LANGDOCK_API_URL = "https://api.langdock.com/anthropic/eu/v1/messages"
LANGDOCK_API_KEY = "sk-0jcTr8heQyZCN86IjIifju1usdBUUp5tBFpmqP5t6D8VusoffpIjNZF6EXo9ZT1R57r2kpmMwpOp46LhqYxpjQ"
TELEGRAM_BOT_TOKEN = "7613213498:AAGmpv4EEt2e5qDzxCx-Jp8IZjPMy1ktkao"

# Идентификатор администратора
ADMIN_ID = 8199808170

# Лимиты использования
MAX_REQUESTS = 30  # Максимальное количество запросов
TIME_WINDOW = 10 * 60 * 60  # 10 часов в секундах

# Хранение истории разговоров для каждого пользователя
conversation_history: Dict[int, List[Dict[str, Any]]] = {}

# Хранение информации о запросах пользователей
user_requests: Dict[int, List[float]] = {}  # user_id -> список временных меток запросов
user_blocked: Dict[int, bool] = {}  # user_id -> статус блокировки
user_custom_limits: Dict[int, int] = {}  # user_id -> персональный лимит запросов

# Состояния пользователей
user_states: Dict[int, str] = {}  # user_id -> текущее состояние (chat, photo_mode, etc.)
waiting_for_photo: Dict[int, bool] = {}  # user_id -> ожидание фото

# Пути к файлам для сохранения данных
USER_REQUESTS_FILE = "user_requests.json"
USER_BLOCKED_FILE = "user_blocked.json"
USER_CUSTOM_LIMITS_FILE = "user_custom_limits.json"

# Добавляем переменную для отслеживания времени последнего сохранения
last_save_time = 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить вступительное сообщение при команде /start."""
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    
    # Инициализация данных пользователя, если их нет
    if user_id not in user_requests:
        user_requests[user_id] = []
    if user_id not in user_blocked:
        user_blocked[user_id] = False
    
    # Создаем красивое вступительное сообщение
    welcome_message = (
        "🌟 *Добро пожаловать в Claude AI Bot!* 🌟\n\n"
        "Я ваш персональный ассистент на базе Claude 3.7 Sonnet - "
        "одной из самых продвинутых моделей искусственного интеллекта.\n\n"
        f"*Лимит запросов:* {MAX_REQUESTS} запросов каждые 10 часов\n\n"
        "Выберите действие в меню ниже ⬇️"
    )
    
    # Создаем меню с обычными кнопками
    keyboard = [
        ["💬 Новый чат", "📸 Анализ фото"],
        ["👤 Мой профиль", "ℹ️ О боте"],
    ]
    
    # Добавляем кнопку администратора, если пользователь - админ
    if user_id == ADMIN_ID:
        keyboard.append(["👑 Панель администратора"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню бота."""
    user_id = update.effective_user.id
    
    # Создаем сообщение главного меню
    menu_message = (
        "🤖 *Главное меню Claude AI Bot*\n\n"
        "Выберите действие из меню ниже ⬇️"
    )
    
    # Создаем меню с обычными кнопками
    keyboard = [
        ["💬 Новый чат", "📸 Анализ фото"],
        ["👤 Мой профиль", "ℹ️ О боте"],
    ]
    
    # Добавляем кнопку администратора, если пользователь - админ
    if user_id == ADMIN_ID:
        keyboard.append(["👑 Панель администратора"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(menu_message, parse_mode='Markdown', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Проверяем, не заблокирован ли пользователь
    if user_id in user_blocked and user_blocked[user_id] and user_id != ADMIN_ID:
        await query.message.reply_text(
            "⛔️ Ваш аккаунт заблокирован администратором. "
            "Пожалуйста, свяжитесь с поддержкой для уточнения деталей."
        )
        return
    
    # Действия с главным меню
    if query.data == "main_menu":
        await main_menu(update, context)
        return
    
    elif query.data == "new_chat":
        # Сбрасываем историю разговора и переходим в режим чата
        conversation_history[user_id] = []
        user_states[user_id] = "chat"
        waiting_for_photo[user_id] = False
        
        keyboard = [
            [InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "💬 *Режим чата активирован*\n\n"
            "Просто напишите мне сообщение или вопрос, и я отвечу вам.\n"
            "История вашего разговора очищена. Начинаем с чистого листа!",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif query.data == "photo_mode":
        # Переходим в режим анализа фото
        user_states[user_id] = "photo_mode"
        waiting_for_photo[user_id] = True
        
        keyboard = [
            [InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "📸 *Режим анализа изображений*\n\n"
            "Отправьте мне фотографию, и я проанализирую её содержимое.\n"
            "Вы можете добавить описание к фотографии для уточнения вопроса.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif query.data == "reset":
        # Сбрасываем историю разговора
        conversation_history[user_id] = []
        
        keyboard = [
            [InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "♻️ *История разговора сброшена*\n\n"
            "Все предыдущие сообщения удалены. Можем начать общение заново!",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif query.data == "about":
        about_text = (
            "*О боте Claude AI*\n\n"
            "Этот бот предоставляет доступ к языковой модели Claude 3.7 Sonnet от Anthropic.\n\n"
            "Claude 3.7 - это передовая модель искусственного интеллекта, способная понимать и "
            "обрабатывать как текст, так и изображения, отличающаяся высокой точностью и "
            "безопасностью ответов.\n\n"
            "*Возможности:*\n"
            "• Отвечать на вопросы по любой теме\n"
            "• Анализировать изображения\n"
            "• Поддерживать длительные беседы\n"
            "• Создавать тексты, стихи, код и многое другое"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(about_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data == "profile":
        # Получаем информацию о пользователе
        user = query.from_user
        username = user.username or "Не указан"
        name = user.full_name or "Не указано"
        
        # Получаем информацию о лимитах пользователя
        limits_info = get_remaining_requests(user_id)
        
        if user_id == ADMIN_ID:
            status = "Администратор"
            requests_info = "Неограниченно (∞)"
        else:
            status = "Пользователь"
            # Форматируем время сброса
            reset_time_str = "не определено"
            if limits_info["reset_time"]:
                hours, remainder = divmod(int(limits_info["reset_time"]), 3600)
                minutes, seconds = divmod(remainder, 60)
                reset_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
            
            requests_info = f"{limits_info['remaining']} из {limits_info['total']} (сброс через {reset_time_str})"
        
        message = (
            "👤 *Ваш профиль*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"👤 Имя: {name}\n"
            f"🔖 Username: @{username}\n"
            f"🛂 Статус: {status}\n"
            f"📊 Доступные запросы: {requests_info}\n"
            f"🔄 Дата регистрации: {time.strftime('%d.%m.%Y', time.localtime())}"
        )
        
        # Создаем кнопки профиля
        keyboard = [
            [InlineKeyboardButton("♻️ Сбросить историю чата", callback_data="reset")],
            [InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    # Админ-панель
    elif query.data == "admin_panel":
        # Проверяем, является ли пользователь администратором
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ У вас нет прав для доступа к админ-панели.", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        # Создаем меню администратора
        keyboard = [
            [InlineKeyboardButton("👥 Статистика пользователей", callback_data="admin_users")],
            [InlineKeyboardButton("🔍 Поиск пользователя", callback_data="admin_search_user")],
            [InlineKeyboardButton("🚫 Блокировки", callback_data="admin_block_menu")],
            [InlineKeyboardButton("📊 Лимиты", callback_data="admin_limits_menu")],
            [InlineKeyboardButton("💾 Сохранить данные", callback_data="admin_save")],
            [InlineKeyboardButton("🔙 Вернуться в меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            "👑 *Панель администратора*\n\n"
            "Выберите нужное действие в меню ниже:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif query.data == "admin_users":
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        # Получаем количество пользователей
        total_users = len(set(conversation_history.keys()) | set(user_requests.keys()))
        blocked_users = sum(1 for is_blocked in user_blocked.values() if is_blocked)
        
        # Получаем общее количество запросов
        total_requests = sum(len(timestamps) for timestamps in user_requests.values())
        
        message = (
            "📊 *Статистика пользователей*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🚫 Заблокировано: {blocked_users}\n"
            f"💬 Всего запросов: {total_requests}\n\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_search_user")],
            [InlineKeyboardButton("🔙 Назад к админ-панели", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data == "admin_search_user":
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        # Устанавливаем состояние ожидания ID пользователя
        user_states[user_id] = "admin_waiting_user_id"
        
        message = (
            "🔍 *Поиск пользователя*\n\n"
            "Введите ID пользователя, информацию о котором хотите получить."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к админ-панели", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data == "admin_block_menu":
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        message = (
            "🚫 *Управление блокировками*\n\n"
            "Для блокировки или разблокировки пользователя, сначала найдите его по ID."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_search_user")],
            [InlineKeyboardButton("🔙 Назад к админ-панели", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data == "admin_limits_menu":
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        message = (
            "📊 *Управление лимитами*\n\n"
            "Для изменения лимитов пользователя, сначала найдите его по ID."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_search_user")],
            [InlineKeyboardButton("🔙 Назад к админ-панели", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    elif query.data == "admin_save":
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        # Сохраняем данные пользователей
        save_user_data()
        
        message = "✅ Данные пользователей успешно сохранены."
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к админ-панели", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(message, reply_markup=reply_markup)
    
    # Обработка действий с конкретными пользователями
    elif query.data.startswith("admin_toggle_block_"):
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        try:
            # Извлекаем ID пользователя из callback_data
            target_user_id = int(query.data.split("_")[-1])
            
            # Переключаем статус блокировки
            current_status = user_blocked.get(target_user_id, False)
            user_blocked[target_user_id] = not current_status
            
            new_status = "заблокирован ⛔️" if user_blocked[target_user_id] else "разблокирован ✅"
            
            await show_user_info(update, context, target_user_id)
            
            await query.message.reply_text(
                f"✅ Пользователь {target_user_id} успешно {new_status}."
            )
        except ValueError:
            await query.message.reply_text("❌ Произошла ошибка при обработке запроса.")
    
    elif query.data.startswith("admin_add_10_"):
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        try:
            # Извлекаем ID пользователя из callback_data
            target_user_id = int(query.data.split("_")[-1])
            
            # Добавляем 10 запросов к лимиту
            current_limit = user_custom_limits.get(target_user_id, MAX_REQUESTS)
            user_custom_limits[target_user_id] = current_limit + 10
            
            await show_user_info(update, context, target_user_id)
            
            await query.message.reply_text(
                f"✅ Пользователю {target_user_id} добавлено 10 запросов.\n"
                f"Новый лимит: {user_custom_limits[target_user_id]} запросов."
            )
        except ValueError:
            await query.message.reply_text("❌ Произошла ошибка при обработке запроса.")
    
    elif query.data.startswith("admin_add_30_"):
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        try:
            # Извлекаем ID пользователя из callback_data
            target_user_id = int(query.data.split("_")[-1])
            
            # Добавляем 30 запросов к лимиту
            current_limit = user_custom_limits.get(target_user_id, MAX_REQUESTS)
            user_custom_limits[target_user_id] = current_limit + 30
            
            await show_user_info(update, context, target_user_id)
            
            await query.message.reply_text(
                f"✅ Пользователю {target_user_id} добавлено 30 запросов.\n"
                f"Новый лимит: {user_custom_limits[target_user_id]} запросов."
            )
        except ValueError:
            await query.message.reply_text("❌ Произошла ошибка при обработке запроса.")
    
    elif query.data.startswith("admin_reset_history_"):
        if user_id != ADMIN_ID:
            await query.message.edit_text("⛔️ Недостаточно прав", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]))
            return
        
        try:
            # Извлекаем ID пользователя из callback_data
            target_user_id = int(query.data.split("_")[-1])
            
            # Сбрасываем историю разговора
            if target_user_id in conversation_history:
                conversation_history[target_user_id] = []
            
            await show_user_info(update, context, target_user_id)
            
            await query.message.reply_text(
                f"✅ История разговора пользователя {target_user_id} успешно сброшена."
            )
        except ValueError:
            await query.message.reply_text("❌ Произошла ошибка при обработке запроса.")

async def show_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> None:
    """Показать информацию о пользователе для администратора."""
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_ID:
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⛔️ У вас нет прав для выполнения этой команды.",
            reply_markup=reply_markup
        )
        return
    
    # Готовим информацию о пользователе
    is_in_history = target_user_id in conversation_history
    is_in_requests = target_user_id in user_requests
    
    if not is_in_history and not is_in_requests:
        keyboard = [["🔍 Поиск пользователя"], ["🔙 Панель администратора"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"❌ Пользователь с ID {target_user_id} не найден.",
            reply_markup=reply_markup
        )
        return
    
    # Получаем информацию о лимитах
    user_limit = user_custom_limits.get(target_user_id, MAX_REQUESTS)
    is_blocked = user_blocked.get(target_user_id, False)
    
    # Считаем количество запросов
    requests_count = len(user_requests.get(target_user_id, []))
    
    message = (
        f"👤 *Информация о пользователе ID: {target_user_id}*\n\n"
        f"🛂 Статус: {'Заблокирован 🚫' if is_blocked else 'Активен ✅'}\n"
        f"📊 Лимит запросов: {user_limit}\n"
        f"💬 Количество запросов: {requests_count}\n"
        f"🔄 История диалогов: {'Есть' if is_in_history else 'Нет'}"
    )
    
    # Сохраняем ID пользователя для работы с ним
    context.user_data["target_user_id"] = target_user_id
    
    # Создаем кнопки управления пользователем
    if is_blocked:
        block_button = "🔓 Разблокировать"
    else:
        block_button = "🔒 Заблокировать"
    
    keyboard = [
        [block_button, "🔄 Сбросить историю"],
        ["➕ Добавить запросы", "➖ Снять запросы"],
        ["🛠 Установить лимит", "🔙 Панель администратора"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Отправляем сообщение с информацией и кнопками
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    # Устанавливаем состояние для работы с этим пользователем
    user_states[user_id] = "admin_viewing_user"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработать текстовые сообщения пользователя и получить ответы от Claude."""
    global last_save_time
    user_id = update.effective_user.id
    
    # Периодическое сохранение данных
    current_time = time.time()
    if current_time - last_save_time > 300:  # 5 минут
        save_user_data()
        last_save_time = current_time
    
    # Если пользователь заблокирован
    if user_id in user_blocked and user_blocked[user_id] and user_id != ADMIN_ID:
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "⛔️ Ваш аккаунт заблокирован администратором. "
            "Пожалуйста, свяжитесь с поддержкой для уточнения деталей.",
            reply_markup=reply_markup
        )
        return
    
    # Обработка команды /start
    if update.message.text.startswith("/start"):
        await start(update, context)
        return
    
    # Обработка команды /admin
    if update.message.text.startswith("/admin") and user_id == ADMIN_ID:
        # Создаем админ-меню
        keyboard = [
            ["👥 Статистика пользователей", "🔍 Поиск пользователя"],
            ["🚫 Блокировки", "📊 Лимиты"],
            ["💾 Сохранить данные", "🔙 Главное меню"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "👑 *Панель администратора*\n\nВыберите нужное действие в меню ниже:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Обработка команды /menu
    if update.message.text.startswith("/menu"):
        await main_menu(update, context)
        return
    
    # Обработка кнопок меню
    if update.message.text == "🔙 Главное меню":
        await main_menu(update, context)
        return
    elif update.message.text == "💬 Новый чат":
        # Сбрасываем историю разговора и переходим в режим чата
        conversation_history[user_id] = []
        user_states[user_id] = "chat"
        waiting_for_photo[user_id] = False
        
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "💬 *Режим чата активирован*\n\n"
            "Просто напишите мне сообщение или вопрос, и я отвечу вам.\n"
            "История вашего разговора очищена. Начинаем с чистого листа!",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    elif update.message.text == "📸 Анализ фото":
        # Переходим в режим анализа фото
        user_states[user_id] = "photo_mode"
        waiting_for_photo[user_id] = True
        
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📸 *Режим анализа изображений*\n\n"
            "Отправьте мне фотографию, и я проанализирую её содержимое.\n"
            "Вы можете добавить описание к фотографии для уточнения вопроса.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    elif update.message.text == "👤 Мой профиль":
        # Получаем информацию о пользователе
        user = update.effective_user
        username = user.username or "Не указан"
        name = user.full_name or "Не указано"
        
        # Получаем информацию о лимитах пользователя
        limits_info = get_remaining_requests(user_id)
        
        if user_id == ADMIN_ID:
            status = "Администратор"
            requests_info = "Неограниченно (∞)"
        else:
            status = "Пользователь"
            # Форматируем время сброса
            reset_time_str = "не определено"
            if limits_info["reset_time"]:
                hours, remainder = divmod(int(limits_info["reset_time"]), 3600)
                minutes, seconds = divmod(remainder, 60)
                reset_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
            
            requests_info = f"{limits_info['remaining']} из {limits_info['total']} (сброс через {reset_time_str})"
        
        message = (
            "👤 *Ваш профиль*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"👤 Имя: {name}\n"
            f"🔖 Username: @{username}\n"
            f"🛂 Статус: {status}\n"
            f"📊 Доступные запросы: {requests_info}\n"
            f"🔄 Дата регистрации: {time.strftime('%d.%m.%Y', time.localtime())}"
        )
        
        # Создаем кнопки профиля
        keyboard = [
            ["♻️ Сбросить историю чата"],
            ["🔙 Главное меню"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        return
    elif update.message.text == "ℹ️ О боте":
        about_text = (
            "*О боте Claude AI*\n\n"
            "Этот бот предоставляет доступ к языковой модели Claude 3.7 Sonnet от Anthropic.\n\n"
            "Claude 3.7 - это передовая модель искусственного интеллекта, способная понимать и "
            "обрабатывать как текст, так и изображения, отличающаяся высокой точностью и "
            "безопасностью ответов.\n\n"
            "*Возможности:*\n"
            "• Отвечать на вопросы по любой теме\n"
            "• Анализировать изображения\n"
            "• Поддерживать длительные беседы\n"
            "• Создавать тексты, стихи, код и многое другое"
        )
        
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(about_text, parse_mode='Markdown', reply_markup=reply_markup)
        return
    elif update.message.text == "♻️ Сбросить историю чата":
        # Сбрасываем историю разговора
        conversation_history[user_id] = []
        
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "♻️ *История разговора сброшена*\n\n"
            "Все предыдущие сообщения удалены. Можем начать общение заново!",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    # Обработка состояния ожидания ID пользователя для админа
    elif user_id == ADMIN_ID and user_id in user_states and user_states[user_id] == "admin_waiting_user_id":
        try:
            target_user_id = int(update.message.text.strip())
            # Сбрасываем состояние
            user_states[user_id] = ""
            # Показываем информацию о пользователе
            await show_user_info(update, context, target_user_id)
        except ValueError:
            keyboard = [["🔙 Панель администратора"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "❌ Неверный формат ID пользователя. Пожалуйста, введите числовой ID.",
                reply_markup=reply_markup
            )
        return
    # Обработка кнопок админ-панели
    elif user_id == ADMIN_ID:
        if update.message.text == "👑 Панель администратора":
            # Создаем меню администратора
            keyboard = [
                ["👥 Статистика пользователей", "🔍 Поиск пользователя"],
                ["🚫 Блокировки", "📊 Лимиты"],
                ["💾 Сохранить данные", "🔙 Главное меню"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "👑 *Панель администратора*\n\n"
                "Выберите нужное действие в меню ниже:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        elif update.message.text == "👥 Статистика пользователей":
            # Получаем количество пользователей
            total_users = len(set(conversation_history.keys()) | set(user_requests.keys()))
            blocked_users = sum(1 for is_blocked in user_blocked.values() if is_blocked)
            
            # Получаем общее количество запросов
            total_requests = sum(len(timestamps) for timestamps in user_requests.values())
            
            message = (
                "📊 *Статистика пользователей*\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"🚫 Заблокировано: {blocked_users}\n"
                f"💬 Всего запросов: {total_requests}\n\n"
            )
            
            keyboard = [
                ["🔍 Поиск пользователя"],
                ["🔙 Панель администратора"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
            return
        elif update.message.text == "🔍 Поиск пользователя":
            # Устанавливаем состояние ожидания ID пользователя
            user_states[user_id] = "admin_waiting_user_id"
            
            message = (
                "🔍 *Поиск пользователя*\n\n"
                "Введите ID пользователя, информацию о котором хотите получить."
            )
            
            keyboard = [
                ["🔙 Назад к админ-панели"],
                ["🔙 Панель администратора"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
            return
        elif update.message.text == "🚫 Блокировки":
            message = (
                "🚫 *Управление блокировками*\n\n"
                "Для блокировки или разблокировки пользователя, сначала найдите его по ID."
            )
            
            keyboard = [
                ["🔍 Поиск пользователя"],
                ["🔙 Панель администратора"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
            return
        elif update.message.text == "📊 Лимиты":
            message = (
                "📊 *Управление лимитами*\n\n"
                "Для изменения лимитов пользователя, сначала найдите его по ID."
            )
            
            keyboard = [
                ["🔍 Поиск пользователя"],
                ["🔙 Панель администратора"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
            return
        elif update.message.text == "💾 Сохранить данные":
            # Сохраняем данные пользователей
            save_user_data()
            
            message = "✅ Данные пользователей успешно сохранены."
            
            keyboard = [["🔙 Панель администратора"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(message, reply_markup=reply_markup)
            return
        elif update.message.text == "🔙 Панель администратора":
            # Возвращаемся в панель администратора
            keyboard = [
                ["👥 Статистика пользователей", "🔍 Поиск пользователя"],
                ["🚫 Блокировки", "📊 Лимиты"],
                ["💾 Сохранить данные", "🔙 Главное меню"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "👑 *Панель администратора*\n\n"
                "Выберите нужное действие в меню ниже:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        # Обработка админских действий над выбранным пользователем
        elif user_states.get(user_id) == "admin_viewing_user" and "target_user_id" in context.user_data:
            target_user_id = context.user_data["target_user_id"]
            
            if update.message.text == "🔒 Заблокировать":
                # Блокируем пользователя
                user_blocked[target_user_id] = True
                
                await update.message.reply_text(
                    f"✅ Пользователь {target_user_id} успешно заблокирован."
                )
                # Показываем обновленную информацию
                await show_user_info(update, context, target_user_id)
                return
            
            elif update.message.text == "🔓 Разблокировать":
                # Разблокируем пользователя
                user_blocked[target_user_id] = False
                
                await update.message.reply_text(
                    f"✅ Пользователь {target_user_id} успешно разблокирован."
                )
                # Показываем обновленную информацию
                await show_user_info(update, context, target_user_id)
                return
            
            elif update.message.text == "🔄 Сбросить историю":
                # Сбрасываем историю разговора
                if target_user_id in conversation_history:
                    conversation_history[target_user_id] = []
                
                await update.message.reply_text(
                    f"✅ История разговора пользователя {target_user_id} успешно сброшена."
                )
                # Показываем обновленную информацию
                await show_user_info(update, context, target_user_id)
                return
            
            # Обработка выбора количества запросов для добавления/снятия/установки
            elif user_states.get(user_id) == "admin_adding_requests" and "target_user_id" in context.user_data:
                target_user_id = context.user_data["target_user_id"]
                
                if update.message.text == "🔙 Отмена":
                    # Возвращаемся к просмотру информации о пользователе
                    await show_user_info(update, context, target_user_id)
                    return
                
                # Парсим количество запросов из текста кнопки
                try:
                    requests_to_add = int(update.message.text.split()[0])
                    
                    # Получаем текущий лимит
                    current_limit = user_custom_limits.get(target_user_id, MAX_REQUESTS)
                    
                    # Устанавливаем новый лимит
                    user_custom_limits[target_user_id] = current_limit + requests_to_add
                    
                    await update.message.reply_text(
                        f"✅ Пользователю {target_user_id} добавлено {requests_to_add} запросов.\n"
                        f"Новый лимит: {user_custom_limits[target_user_id]} запросов."
                    )
                    
                    # Возвращаемся к просмотру информации о пользователе
                    await show_user_info(update, context, target_user_id)
                except (ValueError, IndexError):
                    await update.message.reply_text(
                        "❌ Неверный формат количества запросов. Пожалуйста, выберите из предложенных вариантов."
                    )
                return
                
            elif user_states.get(user_id) == "admin_removing_requests" and "target_user_id" in context.user_data:
                target_user_id = context.user_data["target_user_id"]
                
                if update.message.text == "🔙 Отмена":
                    # Возвращаемся к просмотру информации о пользователе
                    await show_user_info(update, context, target_user_id)
                    return
                
                # Парсим количество запросов из текста кнопки
                try:
                    requests_to_remove = int(update.message.text.split()[0])
                    
                    # Получаем текущий лимит
                    current_limit = user_custom_limits.get(target_user_id, MAX_REQUESTS)
                    
                    # Устанавливаем новый лимит, но не меньше 1
                    new_limit = max(1, current_limit - requests_to_remove)
                    user_custom_limits[target_user_id] = new_limit
                    
                    await update.message.reply_text(
                        f"✅ У пользователя {target_user_id} снято {requests_to_remove} запросов.\n"
                        f"Новый лимит: {user_custom_limits[target_user_id]} запросов."
                    )
                    
                    # Возвращаемся к просмотру информации о пользователе
                    await show_user_info(update, context, target_user_id)
                except (ValueError, IndexError):
                    await update.message.reply_text(
                        "❌ Неверный формат количества запросов. Пожалуйста, выберите из предложенных вариантов."
                    )
                return
                
            elif user_states.get(user_id) == "admin_setting_limit" and "target_user_id" in context.user_data:
                target_user_id = context.user_data["target_user_id"]
                
                if update.message.text == "🔙 Отмена":
                    # Возвращаемся к просмотру информации о пользователе
                    await show_user_info(update, context, target_user_id)
                    return
                
                # Парсим количество запросов из текста кнопки
                try:
                    new_limit = int(update.message.text.split()[0])
                    
                    # Устанавливаем новый лимит
                    user_custom_limits[target_user_id] = new_limit
                    
                    await update.message.reply_text(
                        f"✅ Для пользователя {target_user_id} установлен новый лимит: {new_limit} запросов."
                    )
                    
                    # Возвращаемся к просмотру информации о пользователе
                    await show_user_info(update, context, target_user_id)
                except (ValueError, IndexError):
                    await update.message.reply_text(
                        "❌ Неверный формат лимита запросов. Пожалуйста, выберите из предложенных вариантов."
                    )
                return
    
    # Проверяем лимит пользователя
    if not check_user_limit(user_id):
        limits_info = get_remaining_requests(user_id)
        
        # Форматируем время сброса
        reset_time_str = "не определено"
        if limits_info["reset_time"]:
            hours, remainder = divmod(int(limits_info["reset_time"]), 3600)
            minutes, seconds = divmod(remainder, 60)
            reset_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        
        keyboard = [["👤 Мой профиль"], ["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ *Превышен лимит запросов*\n\n"
            f"Вы использовали все доступные {limits_info['total']} запросов.\n"
            f"Следующий сброс лимита через: {reset_time_str}",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Если пользователь в режиме ожидания фото, но отправил текст
    if user_id in waiting_for_photo and waiting_for_photo[user_id]:
        keyboard = [
            ["📸 Остаться в режиме фото", "💬 Перейти в режим чата"],
            ["🔙 Главное меню"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "ℹ️ Вы находитесь в режиме анализа фото, но отправили текст.\n"
            "Хотите перейти в режим чата или остаться в режиме фото?",
            reply_markup=reply_markup
        )
        return
    
    # Инициализация истории разговора для новых пользователей
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    
    # Устанавливаем режим чата, если еще не установлен
    if user_id not in user_states or not user_states[user_id]:
        user_states[user_id] = "chat"
    
    user_message = update.message.text
    logger.info(f"Получено сообщение от пользователя {user_id}: {user_message}")
    
    # Отправка статуса "печатает..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Добавляем историю разговора, если она есть
        messages = []
        if len(conversation_history[user_id]) > 0:
            messages = conversation_history[user_id][-10:]  # Берем последние 10 сообщений из истории
        
        # Добавляем текущее сообщение пользователя
        messages.append({"role": "user", "content": user_message})
        
        # Подготовка запроса к API Claude
        payload = {
            "model": "claude-3-7-sonnet-20250219",
            "messages": messages,
            "max_tokens": 4000,  # Увеличиваем максимальное количество токенов
            "temperature": 0.7
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": LANGDOCK_API_KEY,
            "anthropic-version": "2023-06-01"
        }
        
        logger.info(f"Отправка запроса к Claude API: {json.dumps(payload)}")
        
        # Отправка запроса к API Claude
        response = requests.post(LANGDOCK_API_URL, json=payload, headers=headers)
        
        # Логирование ответа для отладки
        logger.info(f"Код ответа от API: {response.status_code}")
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                
                # Извлечение ответа Claude
                if "content" in response_data and len(response_data["content"]) > 0:
                    claude_response = response_data["content"][0]["text"]
                    
                    # Сохраняем историю разговора
                    conversation_history[user_id].append({"role": "user", "content": user_message})
                    conversation_history[user_id].append({"role": "assistant", "content": claude_response})
                    
                    # Ограничиваем историю до 10 сообщений (5 вопросов и 5 ответов)
                    if len(conversation_history[user_id]) > 20:
                        conversation_history[user_id] = conversation_history[user_id][-20:]
                    
                    # Проверяем длину ответа и разбиваем при необходимости
                    if len(claude_response) > 4000:  # Телеграм ограничивает сообщения ~4096 символами
                        # Разбиваем ответ на части по 4000 символов
                        chunks = [claude_response[i:i+4000] for i in range(0, len(claude_response), 4000)]
                        
                        # Отправляем первую часть с кнопками
                        keyboard = [
                            ["♻️ Сбросить чат", "🔙 Главное меню"]
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        await update.message.reply_text(
                            f"{chunks[0]}\n\n(Часть 1/{len(chunks)})",
                            reply_markup=reply_markup
                        )
                        
                        # Отправляем остальные части
                        for i, chunk in enumerate(chunks[1:], 2):
                            await update.message.reply_text(
                                f"{chunk}\n\n(Часть {i}/{len(chunks)})"
                            )
                    else:
                        # Добавляем кнопки к ответу
                        keyboard = [
                            ["♻️ Сбросить чат", "🔙 Главное меню"]
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        # Отправка обычного ответа
                        await update.message.reply_text(claude_response, reply_markup=reply_markup)
                else:
                    claude_response = "Получен пустой ответ от API. Пожалуйста, попробуйте еще раз."
                    keyboard = [["🔙 Главное меню"]]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    await update.message.reply_text(claude_response, reply_markup=reply_markup)
            except json.JSONDecodeError:
                claude_response = "Ошибка декодирования JSON ответа. Пожалуйста, попробуйте еще раз."
                keyboard = [["🔙 Главное меню"]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(claude_response, reply_markup=reply_markup)
        else:
            claude_response = f"Ошибка API: {response.status_code}. Пожалуйста, попробуйте еще раз."
            keyboard = [["🔙 Главное меню"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(claude_response, reply_markup=reply_markup)
        
        # Обновляем счетчик запросов пользователя
        update_user_requests(user_id)
        
    except Exception as e:
        logger.error(f"Произошла ошибка: {str(e)}")
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"Произошла ошибка: {str(e)}",
            reply_markup=reply_markup
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработать фотографии от пользователя."""
    global last_save_time
    user_id = update.effective_user.id
    
    # Периодическое сохранение данных
    current_time = time.time()
    if current_time - last_save_time > 300:  # 5 минут
        save_user_data()
        last_save_time = current_time
    
    # Если пользователь заблокирован
    if user_id in user_blocked and user_blocked[user_id] and user_id != ADMIN_ID:
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⛔️ Ваш аккаунт заблокирован администратором. "
            "Пожалуйста, свяжитесь с поддержкой для уточнения деталей.",
            reply_markup=reply_markup
        )
        return
    
    # Проверяем лимит пользователя
    if not check_user_limit(user_id):
        limits_info = get_remaining_requests(user_id)
        
        # Форматируем время сброса
        reset_time_str = "не определено"
        if limits_info["reset_time"]:
            hours, remainder = divmod(int(limits_info["reset_time"]), 3600)
            minutes, seconds = divmod(remainder, 60)
            reset_time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
        
        keyboard = [["👤 Мой профиль"], ["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ *Превышен лимит запросов*\n\n"
            f"Вы использовали все доступные {limits_info['total']} запросов.\n"
            f"Следующий сброс лимита через: {reset_time_str}",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # Устанавливаем режим фото
    user_states[user_id] = "photo_mode"
    waiting_for_photo[user_id] = False
    
    # Инициализация истории разговора для новых пользователей
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    
    # Получаем наилучшее качество фото
    photo_file = await update.message.photo[-1].get_file()
    
    # Отправка статуса "печатает..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Скачиваем фото
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Получаем текст если есть подпись к фото
        caption = update.message.caption or "Что на этом изображении?"
        
        # Кодируем фото в base64
        image_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Подготовка запроса к API Claude с фото
        payload = {
            "model": "claude-3-7-sonnet-20250219",
            "messages": [
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": caption},
                        {
                            "type": "image", 
                            "source": {
                                "type": "base64", 
                                "media_type": "image/jpeg", 
                                "data": image_base64
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 4000,  # Увеличиваем максимальное количество токенов
            "temperature": 0.7
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": LANGDOCK_API_KEY,
            "anthropic-version": "2023-06-01"
        }
        
        logger.info(f"Отправка запроса к Claude API с изображением")
        
        # Отправка запроса к API Claude
        response = requests.post(LANGDOCK_API_URL, json=payload, headers=headers)
        
        # Логирование ответа для отладки
        logger.info(f"Код ответа от API: {response.status_code}")
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                
                # Извлечение ответа Claude
                if "content" in response_data and len(response_data["content"]) > 0:
                    claude_response = response_data["content"][0]["text"]
                    
                    # Сохраняем в историю разговора
                    user_msg = {"role": "user", "content": [{"type": "text", "text": caption}, {"type": "image", "source": "image_data"}]}
                    assistant_msg = {"role": "assistant", "content": claude_response}
                    
                    conversation_history[user_id].append(user_msg)
                    conversation_history[user_id].append(assistant_msg)
                    
                    # Ограничиваем историю до 10 сообщений (5 вопросов и 5 ответов)
                    if len(conversation_history[user_id]) > 20:
                        conversation_history[user_id] = conversation_history[user_id][-20:]
                    
                    # Проверяем длину ответа и разбиваем при необходимости
                    if len(claude_response) > 4000:  # Телеграм ограничивает сообщения ~4096 символами
                        # Разбиваем ответ на части по 4000 символов
                        chunks = [claude_response[i:i+4000] for i in range(0, len(claude_response), 4000)]
                        
                        # Отправляем первую часть с кнопками
                        keyboard = [
                            ["📸 Еще фото", "💬 Режим чата"],
                            ["🔙 Главное меню"]
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        await update.message.reply_text(
                            f"{chunks[0]}\n\n(Часть 1/{len(chunks)})",
                            reply_markup=reply_markup
                        )
                        
                        # Отправляем остальные части
                        for i, chunk in enumerate(chunks[1:], 2):
                            await update.message.reply_text(
                                f"{chunk}\n\n(Часть {i}/{len(chunks)})"
                            )
                    else:
                        # Добавляем кнопки для интерфейса
                        keyboard = [
                            ["📸 Еще фото", "💬 Режим чата"],
                            ["🔙 Главное меню"]
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        # Отправка обычного ответа
                        await update.message.reply_text(claude_response, reply_markup=reply_markup)
                else:
                    claude_response = "Получен пустой ответ от API. Пожалуйста, попробуйте еще раз."
                    keyboard = [["🔙 Главное меню"]]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    await update.message.reply_text(claude_response, reply_markup=reply_markup)
            except json.JSONDecodeError:
                claude_response = "Ошибка декодирования JSON ответа. Пожалуйста, попробуйте еще раз."
                keyboard = [["🔙 Главное меню"]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(claude_response, reply_markup=reply_markup)
        else:
            claude_response = f"Ошибка API: {response.status_code}. Пожалуйста, попробуйте еще раз."
            keyboard = [["🔙 Главное меню"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(claude_response, reply_markup=reply_markup)
        
        # Обновляем счетчик запросов пользователя
        update_user_requests(user_id)
        
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке фото: {str(e)}")
        keyboard = [["🔙 Главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"Произошла ошибка при обработке фото: {str(e)}",
            reply_markup=reply_markup
        )

def check_user_limit(user_id: int) -> bool:
    """Проверить, не превысил ли пользователь лимит запросов.
    
    Returns:
        bool: True если пользователь может отправить запрос, False в противном случае
    """
    # Администратор имеет неограниченный доступ
    if user_id == ADMIN_ID:
        return True
    
    # Проверяем, не заблокирован ли пользователь вручную
    if user_id in user_blocked and user_blocked[user_id]:
        return False
    
    # Если пользователя нет в базе, инициализируем его данные
    if user_id not in user_requests:
        user_requests[user_id] = []
    
    # Текущее время
    current_time = time.time()
    
    # Удаляем запросы старше TIME_WINDOW
    user_requests[user_id] = [t for t in user_requests[user_id] if current_time - t < TIME_WINDOW]
    
    # Получаем лимит пользователя (стандартный или персональный)
    user_limit = user_custom_limits.get(user_id, MAX_REQUESTS)
    
    # Проверяем, не превышен ли лимит
    return len(user_requests[user_id]) < user_limit

def update_user_requests(user_id: int) -> None:
    """Добавить новый запрос пользователя в счетчик."""
    if user_id not in user_requests:
        user_requests[user_id] = []
    
    user_requests[user_id].append(time.time())

def get_remaining_requests(user_id: int) -> Dict[str, Any]:
    """Получить информацию об оставшихся запросах пользователя."""
    # Администратор имеет неограниченный доступ
    if user_id == ADMIN_ID:
        return {
            "remaining": "∞",
            "total": "∞",
            "reset_time": None
        }
    
    # Если пользователя нет в базе, инициализируем его данные
    if user_id not in user_requests:
        user_requests[user_id] = []
    
    # Текущее время
    current_time = time.time()
    
    # Удаляем запросы старше TIME_WINDOW
    user_requests[user_id] = [t for t in user_requests[user_id] if current_time - t < TIME_WINDOW]
    
    # Получаем лимит пользователя (стандартный или персональный)
    user_limit = user_custom_limits.get(user_id, MAX_REQUESTS)
    
    # Рассчитываем оставшиеся запросы
    used_requests = len(user_requests[user_id])
    remaining_requests = user_limit - used_requests
    
    # Находим время сброса (время самого раннего запроса + TIME_WINDOW)
    reset_time = None
    if user_requests[user_id]:
        oldest_request = min(user_requests[user_id])
        reset_time = oldest_request + TIME_WINDOW - current_time
    
    return {
        "remaining": remaining_requests,
        "total": user_limit,
        "reset_time": reset_time
    }

def save_user_data() -> None:
    """Сохранить данные о пользователях в файлы."""
    try:
        # Преобразуем временные метки в строки для сохранения в JSON
        serializable_requests = {}
        for user_id, timestamps in user_requests.items():
            serializable_requests[str(user_id)] = timestamps
        
        # Сохраняем запросы пользователей
        with open(USER_REQUESTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_requests, f)
        
        # Сохраняем статусы блокировки
        serializable_blocked = {}
        for user_id, is_blocked in user_blocked.items():
            serializable_blocked[str(user_id)] = is_blocked
        
        with open(USER_BLOCKED_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_blocked, f)
        
        # Сохраняем персональные лимиты
        serializable_limits = {}
        for user_id, limit in user_custom_limits.items():
            serializable_limits[str(user_id)] = limit
        
        with open(USER_CUSTOM_LIMITS_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_limits, f)
        
        logger.info("Данные пользователей успешно сохранены")
    
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных пользователей: {str(e)}")

def load_user_data() -> None:
    """Загрузить данные о пользователях из файлов."""
    global user_requests, user_blocked, user_custom_limits
    
    try:
        # Загружаем запросы пользователей
        if os.path.exists(USER_REQUESTS_FILE):
            with open(USER_REQUESTS_FILE, 'r', encoding='utf-8') as f:
                serializable_requests = json.load(f)
                
                for user_id_str, timestamps in serializable_requests.items():
                    user_requests[int(user_id_str)] = timestamps
        
        # Загружаем статусы блокировки
        if os.path.exists(USER_BLOCKED_FILE):
            with open(USER_BLOCKED_FILE, 'r', encoding='utf-8') as f:
                serializable_blocked = json.load(f)
                
                for user_id_str, is_blocked in serializable_blocked.items():
                    user_blocked[int(user_id_str)] = is_blocked
        
        # Загружаем персональные лимиты
        if os.path.exists(USER_CUSTOM_LIMITS_FILE):
            with open(USER_CUSTOM_LIMITS_FILE, 'r', encoding='utf-8') as f:
                serializable_limits = json.load(f)
                
                for user_id_str, limit in serializable_limits.items():
                    user_custom_limits[int(user_id_str)] = limit
        
        logger.info("Данные пользователей успешно загружены")
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных пользователей: {str(e)}")
        # Инициализируем пустые словари, если произошла ошибка
        user_requests = {}
        user_blocked = {}
        user_custom_limits = {}

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок для приложения."""
    # Обрабатываем только нужные ошибки
    if isinstance(context.error, telegram.error.Conflict):
        logger.error("Конфликт: другой экземпляр бота все еще запущен.")
        logger.info("Принудительное завершение работы всех экземпляров Python...")
        # Используем системную функцию для жесткого завершения
        os._exit(1)
    else:
        logger.error(f"Ошибка: {str(context.error)}")

def main() -> None:
    """Запуск бота."""
    # Завершаем другие экземпляры перед запуском
    logger.info("Поиск и завершение уже запущенных экземпляров бота...")
    kill_other_instances()
    
    # Небольшая пауза, чтобы убедиться, что все процессы завершены
    time.sleep(1)
    
    # Загружаем данные пользователей при запуске
    load_user_data()
    
    # Инициализация времени последнего сохранения
    global last_save_time
    last_save_time = time.time()
    
    # Создание приложения
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", main_menu))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))

    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)

    try:
        # Запуск бота до нажатия пользователем Ctrl-C
        logger.info("Бот запущен и готов к работе! ID администратора: %s", ADMIN_ID)
        print("=" * 50)
        print("   🤖 Claude AI Bot запущен и готов к работе!   ")
        print("=" * 50)
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        # Сохраняем данные при завершении
        logger.info("Сохранение данных перед выходом...")
        save_user_data()
        logger.info("Завершение работы бота.")

if __name__ == "__main__":
    main() 
