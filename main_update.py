from voice_handler import handle_voice_message

# Добавить в функцию main() после регистрации других обработчиков 
# (сразу перед application.add_error_handler(error_handler)):

# Обработчик голосовых сообщений
application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
logger.info("Зарегистрирован обработчик голосовых сообщений")

# Если вы хотите также обрабатывать распознанный текст через существующую функцию handle_message,
# измените функцию handle_voice_message в файле voice_handler.py, добавив в конец:

"""
# Создаем фейковый объект сообщения с распознанным текстом
class FakeMessage:
    def __init__(self, text, chat_id):
        self.text = text
        self.chat_id = chat_id

# Создаем обновление с текстом вместо голосового сообщения
fake_update = Update._get_empty_object()
fake_update._unfreeze()
fake_update.effective_user = update.effective_user
fake_update.effective_chat = update.effective_chat
fake_update.message = FakeMessage(recognized_text, update.effective_chat.id)
fake_update._freeze()

# Обрабатываем текст как обычное сообщение
await handle_message(fake_update, context)
"""

# Дополнительные настройки для Whisper (если вы решите его использовать вместо Google Speech Recognition)
"""
# Для использования OpenAI Whisper в voice_handler.py:
import whisper

# Загружаем модель (только один раз при запуске)
model = whisper.load_model("base")  # или tiny, small, medium, large

# И затем замените функцию recognize_speech:
async def recognize_speech_with_whisper(audio_file_path):
    try:
        result = model.transcribe(audio_file_path)
        text = result["text"]
        logger.info(f"Распознан текст с помощью Whisper: {text}")
        return text
    except Exception as e:
        logger.error(f"Ошибка при распознавании речи Whisper: {str(e)}")
        return "Произошла ошибка при обработке голосового сообщения"
""" 