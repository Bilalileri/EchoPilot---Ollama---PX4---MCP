import speech_recognition as sr
import logging

def listen_for_command(timeout=5, phrase_time_limit=10):
    """Listens for a voice command and returns it as text."""
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n" + "="*25)
        print("🎤 Calibrating... Please be quiet for a moment.")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("Say your command now...")
        print("="*25)
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            print("✅ Audio captured, recognizing...")
            command = recognizer.recognize_google(audio)
            print(f"👤 YOU SAID: {command}")
            return command.lower()
        except sr.WaitTimeoutError:
            print("👂 Listening timed out.")
            return None
        except sr.UnknownValueError:
            print("❌ Could not understand the audio.")
            return None
        except Exception as e:
            logging.error(f"An unexpected error in voice recognition: {e}")
            return None