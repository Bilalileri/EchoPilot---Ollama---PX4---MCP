import pyttsx3
import logging

class Speaker:
    """
    Handles Text-to-Speech (TTS) operations using the offline pyttsx3 engine.
    """
    def __init__(self):
        try:
            self.engine = pyttsx3.init()
            voices = self.engine.getProperty('voices')
            # voices[1] is often a female voice on many systems.
            # You can experiment by changing the index.
            self.engine.setProperty('voice', voices[1].id)
            self.engine.setProperty('rate', 150)
            print("🔊 Offline TTS Speaker (pyttsx3) initialized.")
        except Exception as e:
            logging.error(f"Failed to initialize pyttsx3 engine: {e}")
            self.engine = None

    def say(self, text):
        """Speaks the given text using the TTS engine."""
        print(f"🤖 DRONE SAYS: {text}")
        if self.engine:
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                logging.error(f"TTS failed to say '{text}': {e}")

# Create a single, shared instance.
speaker = Speaker()