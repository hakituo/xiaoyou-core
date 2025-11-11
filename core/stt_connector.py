import os
import logging
import speech_recognition as sr
import tempfile
from pydub import AudioSegment

# Configure logger
logger = logging.getLogger(__name__)

class STTConnector:
    """
    Speech-to-Text connector for processing audio files
    """
    
    def __init__(self):
        self.recognizer = sr.Recognizer()
        # Configure recognizer settings
        self.recognizer.energy_threshold = 300  # Adjust based on ambient noise
        self.recognizer.dynamic_energy_threshold = True
    
    def convert_audio_to_text(self, audio_path, language='zh-CN'):
        """
        Convert audio file to text
        
        Args:
            audio_path: Path to the audio file
            language: Language code (default is Chinese)
        
        Returns:
            str: Transcribed text
        """
        try:
            # Check if file exists
            if not os.path.exists(audio_path):
                logger.error(f"Audio file not found: {audio_path}")
                return "Error: Audio file not found"
            
            # Convert to WAV format if needed
            wav_path = self._convert_to_wav(audio_path)
            
            # Recognize speech using Google Speech Recognition
            with sr.AudioFile(wav_path) as source:
                audio_data = self.recognizer.record(source)
                text = self.recognizer.recognize_google(audio_data, language=language)
                
            logger.info(f"Successfully transcribed audio to text: {text[:50]}...")
            return text
        
        except sr.UnknownValueError:
            logger.warning("Could not understand audio")
            return "Error: Could not understand audio"
        except sr.RequestError as e:
            logger.error(f"Could not request results from speech recognition service: {e}")
            return f"Error: Speech recognition service error: {str(e)}"
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            return f"Error processing audio: {str(e)}"
        finally:
            # Clean up temporary files
            if 'wav_path' in locals() and wav_path != audio_path:
                try:
                    os.remove(wav_path)
                except:
                    pass
    
    def _convert_to_wav(self, audio_path):
        """
        Convert audio file to WAV format if it's not already
        
        Args:
            audio_path: Path to the audio file
        
        Returns:
            str: Path to the WAV file
        """
        _, ext = os.path.splitext(audio_path)
        if ext.lower() == '.wav':
            return audio_path
        
        try:
            # Create temporary WAV file
            temp_fd, wav_path = tempfile.mkstemp(suffix='.wav')
            os.close(temp_fd)
            
            # Convert to WAV
            audio = AudioSegment.from_file(audio_path)
            audio.export(wav_path, format='wav')
            
            logger.info(f"Converted {audio_path} to WAV format")
            return wav_path
        except Exception as e:
            logger.error(f"Failed to convert audio to WAV: {e}")
            # If conversion fails, try to use the original file directly
            return audio_path
    
    def process_audio_from_bytes(self, audio_bytes, file_extension, language='zh-CN'):
        """
        Process audio from bytes
        
        Args:
            audio_bytes: Audio data as bytes
            file_extension: Original file extension
            language: Language code
        
        Returns:
            str: Transcribed text
        """
        try:
            # Create temporary file
            temp_fd, temp_path = tempfile.mkstemp(suffix=f'.{file_extension}')
            os.close(temp_fd)
            
            # Write audio bytes to file
            with open(temp_path, 'wb') as f:
                f.write(audio_bytes)
            
            # Process the audio file
            text = self.convert_audio_to_text(temp_path, language)
            return text
        finally:
            # Clean up
            if 'temp_path' in locals():
                try:
                    os.remove(temp_path)
                except:
                    pass

# Create a global instance for convenience
stt_connector = STTConnector()

# Helper function for direct use
def transcribe_audio(audio_path, language='zh-CN'):
    """
    Helper function to transcribe audio
    
    Args:
        audio_path: Path to the audio file
        language: Language code
    
    Returns:
        str: Transcribed text
    """
    return stt_connector.convert_audio_to_text(audio_path, language)