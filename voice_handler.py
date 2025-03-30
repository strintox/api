import os
import logging
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
from telegram import Update
from telegram.ext import ContextTypes

# Настройка логирования
logger = logging.getLogger(__name__)

async def convert_ogg_to_wav(ogg_file_path):
    """Конвертирует аудиофайл из формата OGG в WAV."""
    try:
        # Создаем временный файл для WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            wav_file_path = temp_wav.name
        
        # Конвертация из OGG в WAV используя pydub
        audio = AudioSegment.from_ogg(ogg_file_path)
        audio.export(wav_file_path, format="wav")
        
        logger.info(f"Успешно конвертирован файл из OGG в WAV: {wav_file_path}")
        return wav_file_path
    except Exception as e:
        logger.error(f"Ошибка при конвертации аудио: {str(e)}")
        return None

async def recognize_speech(audio_file_path):
    """Распознает речь в аудиофайле."""
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_file_path) as source:
            # Настраиваем распознавание шума
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # Получаем аудиоданные
            audio_data = recognizer.record(source)
            
            # Пытаемся распознать речь (сначала на русском, затем на английском)
            try:
                text = recognizer.recognize_google(audio_data, language="ru-RU")
                logger.info(f"Распознан русский текст: {text}")
            except:
                try:
                    text = recognizer.recognize_google(audio_data, language="en-US")
                    logger.info(f"Распознан английский текст: {text}")
                except sr.UnknownValueError:
                    logger.warning("Не удалось распознать речь")
                    return "Не удалось распознать речь. Пожалуйста, говорите чётче или отправьте текстовое сообщение."
                except sr.RequestError as e:
                    logger.error(f"Ошибка сервиса распознавания речи: {str(e)}")
                    return "Произошла ошибка при обращении к сервису распознавания речи. Пожалуйста, попробуйте позже."
            
            return text
    except Exception as e:
        logger.error(f"Ошибка при распознавании речи: {str(e)}")
        return "Произошла ошибка при обработке голосового сообщения. Пожалуйста, попробуйте еще раз."

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает голосовые сообщения."""
    user_id = update.effective_user.id
    
    # Отправляем статус "печатает..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Сообщаем, что начали обработку
    processing_message = await update.message.reply_text(
        "🎤 Обрабатываю ваше голосовое сообщение...",
    )
    
    try:
        # Получаем файл голосового сообщения
        voice_file = await update.message.voice.get_file()
        
        # Создаем временный файл для OGG
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
            ogg_file_path = temp_ogg.name
        
        # Скачиваем файл голосового сообщения
        await voice_file.download_to_drive(ogg_file_path)
        logger.info(f"Скачан файл голосового сообщения: {ogg_file_path}")
        
        # Конвертируем OGG в WAV
        wav_file_path = await convert_ogg_to_wav(ogg_file_path)
        if not wav_file_path:
            await processing_message.edit_text("❌ Не удалось обработать аудиофайл. Пожалуйста, попробуйте еще раз.")
            return
        
        # Распознаем речь
        recognized_text = await recognize_speech(wav_file_path)
        
        # Удаляем сообщение об обработке
        await processing_message.delete()
        
        # Отправляем распознанный текст
        await update.message.reply_text(
            f"🔊 Распознанный текст: \n\n{recognized_text}",
            reply_to_message_id=update.message.message_id
        )
        
        # Теперь обрабатываем этот текст как обычное сообщение
        # Ниже добавьте вызов вашей функции для обработки текстовых сообщений
        # например: await handle_message(update, context, recognized_text)
        
        # Очищаем временные файлы
        try:
            os.remove(ogg_file_path)
            os.remove(wav_file_path)
        except Exception as e:
            logger.warning(f"Не удалось удалить временные файлы: {str(e)}")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке голосового сообщения: {str(e)}")
        await processing_message.edit_text("❌ Произошла ошибка при обработке голосового сообщения. Пожалуйста, попробуйте позже.") 