# Добавление поддержки голосовых сообщений в Telegram бота

## Общее описание
Эта функция позволяет боту обрабатывать голосовые сообщения от пользователей. Бот будет распознавать речь с помощью Google Speech Recognition или OpenAI Whisper, преобразовывать её в текст, и затем обрабатывать этот текст как обычное текстовое сообщение.

## Установка зависимостей

Необходимо установить дополнительные библиотеки:

```bash
pip install -r requirements.txt
```

Также необходимо установить ffmpeg:

На Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

На Windows:
1. Скачайте ffmpeg с официального сайта https://ffmpeg.org/download.html
2. Распакуйте архив
3. Добавьте путь к папке bin в переменную PATH

## Интеграция в бота

### Шаг 1: Добавьте файл voice_handler.py

Этот файл уже создан и содержит все необходимые функции для обработки голосовых сообщений.

### Шаг 2: Обновите main.py

Добавьте в верхнюю часть файла main.py следующий импорт:
```python
from voice_handler import handle_voice_message
```

В функции main(), после регистрации других обработчиков, добавьте:
```python
# Обработчик голосовых сообщений
application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
logger.info("Зарегистрирован обработчик голосовых сообщений")
```

### Шаг 3 (опционально): Настройка обработки распознанного текста

Если вы хотите, чтобы распознанный текст обрабатывался через вашу существующую функцию handle_message, 
добавьте в конец функции handle_voice_message в файле voice_handler.py следующий код:

```python
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
```

Не забудьте добавить импорт:
```python
from handlers import handle_message  # замените на правильный путь к вашей функции обработки сообщений
```

## Использование OpenAI Whisper (опционально)

Если вы хотите использовать OpenAI Whisper вместо Google Speech Recognition для более точного распознавания речи,
добавьте в файл voice_handler.py следующий код:

```python
import whisper

# Загружаем модель (только один раз при запуске)
model = whisper.load_model("base")  # или tiny, small, medium, large

async def recognize_speech_with_whisper(audio_file_path):
    try:
        result = model.transcribe(audio_file_path)
        text = result["text"]
        logger.info(f"Распознан текст с помощью Whisper: {text}")
        return text
    except Exception as e:
        logger.error(f"Ошибка при распознавании речи Whisper: {str(e)}")
        return "Произошла ошибка при обработке голосового сообщения"
```

И затем замените вызов `recognized_text = await recognize_speech(wav_file_path)` 
на `recognized_text = await recognize_speech_with_whisper(wav_file_path)` в функции handle_voice_message.

## Примечания по работе

- Голосовые сообщения ограничены по длительности в Telegram (до 1 минуты для обычных пользователей).
- Google Speech Recognition имеет ограничения на количество запросов в день для бесплатного использования.
- OpenAI Whisper работает локально и не имеет таких ограничений, но требует больше вычислительных ресурсов.
- Обработка голосовых сообщений может занимать некоторое время в зависимости от длительности сообщения и используемого сервиса распознавания.

## Проверка работоспособности

Для проверки работы отправьте голосовое сообщение боту. Вы должны получить ответ с распознанным текстом и ответом от Claude API, если настроили обработку распознанного текста. 