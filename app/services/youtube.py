import logging
import uuid
from pathlib import Path
from typing import Optional

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError


logger = logging.getLogger(__name__)


class YouTubeServiceError(Exception):
    """Base exception for YouTube service errors"""
    pass


class VideoUnavailableError(YouTubeServiceError):
    """Video is unavailable, private, or deleted"""
    pass


class VideoRestrictedError(YouTubeServiceError):
    """Video is age-restricted or geo-blocked"""
    pass


class VideoDownloadError(YouTubeServiceError):
    """Error during video download"""
    pass


class YouTubeService:
    """Service for downloading audio from YouTube videos"""

    def __init__(self, max_duration: int = 1800, audio_quality: str = "best"):
        """
        Initialize YouTube service

        Args:
            max_duration: Maximum video duration in seconds (default: 1800 = 30 min)
            audio_quality: Audio quality preference (default: best)
        """
        self.max_duration = max_duration
        self.audio_quality = audio_quality
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)

    def _get_video_info(self, url: str) -> dict:
        """Get video information without downloading"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info

    def check_duration(self, url: str) -> tuple[bool, Optional[int]]:
        """
        Check if video duration is within allowed limit

        Returns:
            Tuple of (is_valid, duration_in_seconds)

        Raises:
            VideoUnavailableError: If video is not available
            VideoRestrictedError: If video is restricted
        """
        try:
            info = self._get_video_info(url)
            duration = info.get('duration')

            # Handle None duration (livestreams, premieres)
            if duration is None:
                logger.warning("Video has no duration (might be a livestream)")
                return False, None

            if duration > self.max_duration:
                return False, duration

            return True, duration
        except ExtractorError as e:
            error_msg = str(e).lower()
            if 'private' in error_msg or 'unavailable' in error_msg or 'deleted' in error_msg:
                logger.error(f"Video unavailable: {e}")
                raise VideoUnavailableError("Видео недоступно, удалено или приватное")
            elif 'age' in error_msg or 'restricted' in error_msg or 'geo' in error_msg:
                logger.error(f"Video restricted: {e}")
                raise VideoRestrictedError("Видео имеет ограничения (возраст/регион)")
            else:
                logger.error(f"Extractor error: {e}")
                raise VideoUnavailableError(f"Ошибка при получении информации о видео")
        except DownloadError as e:
            logger.error(f"Download error: {e}")
            raise VideoUnavailableError("Не удалось получить доступ к видео")
        except Exception as e:
            logger.error(f"Error checking video duration: {e}")
            raise YouTubeServiceError(f"Неожиданная ошибка: {str(e)}")

    def download_and_convert(self, url: str) -> tuple[Path, str, int]:
        """
        Download audio from YouTube video (without conversion)

        Args:
            url: YouTube video URL

        Returns:
            Tuple of (Path to the downloaded audio file, Video title, Duration in seconds)

        Raises:
            VideoUnavailableError: If video is not available
            VideoRestrictedError: If video is restricted
            VideoDownloadError: If download fails
        """
        try:
            # Generate unique filename to avoid conflicts
            unique_id = uuid.uuid4().hex[:8]

            # Configure yt-dlp options - extract audio without re-encoding
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'nopostoverwrites': False,
                }],
                'outtmpl': str(self.download_dir / f'{unique_id}_%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 3,
                'skip_unavailable_fragments': True,
                'nocheckcertificate': True,
                'prefer_free_formats': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['webpage', 'configs'],
                    }
                },
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download audio directly
                info = ydl.extract_info(url, download=True)

                # Get the output file path, title, and duration
                filename = ydl.prepare_filename(info)
                # After FFmpegExtractAudio, extension changes to audio format
                base_path = Path(filename).with_suffix('')
                video_title = info.get('title', 'audio')
                duration = info.get('duration', 0)

                # Find the actual audio file (could be .m4a, .opus, .webm, etc)
                audio_file = None
                for ext in ['.m4a', '.opus', '.webm', '.mp3', '.ogg']:
                    potential_file = base_path.with_suffix(ext)
                    if potential_file.exists():
                        audio_file = potential_file
                        break

                if not audio_file or not audio_file.exists():
                    raise FileNotFoundError(f"Audio file not found: {base_path}")

                # Check if file is empty
                if audio_file.stat().st_size == 0:
                    audio_file.unlink()
                    raise VideoDownloadError("Загруженный файл пуст")

                logger.info(f"Successfully downloaded: {audio_file}")
                return audio_file, video_title, duration

        except (VideoUnavailableError, VideoRestrictedError, VideoDownloadError):
            # Re-raise our custom exceptions
            raise
        except ExtractorError as e:
            error_msg = str(e).lower()
            if 'private' in error_msg or 'unavailable' in error_msg or 'deleted' in error_msg:
                logger.error(f"Video unavailable during download: {e}")
                raise VideoUnavailableError("Видео недоступно, удалено или приватное")
            elif 'age' in error_msg or 'restricted' in error_msg or 'geo' in error_msg:
                logger.error(f"Video restricted during download: {e}")
                raise VideoRestrictedError("Видео имеет ограничения по возрасту или региону")
            elif 'empty' in error_msg or 'fragment' in error_msg:
                logger.error(f"Download incomplete: {e}")
                raise VideoDownloadError("Не удалось скачать видео полностью. Попробуйте другое видео.")
            else:
                logger.error(f"Extractor error during download: {e}")
                raise VideoDownloadError(f"Ошибка при скачивании видео")
        except DownloadError as e:
            error_msg = str(e).lower()
            if 'empty' in error_msg:
                logger.error(f"Empty file error: {e}")
                raise VideoDownloadError("Загруженный файл пуст. Возможно, видео защищено или недоступно.")
            else:
                logger.error(f"Download error: {e}")
                raise VideoDownloadError("Ошибка при загрузке видео")
        except FileNotFoundError as e:
            logger.error(f"File not found after download: {e}")
            raise VideoDownloadError("Не удалось скачать аудио файл")
        except Exception as e:
            logger.error(f"Unexpected error during download: {e}")
            raise VideoDownloadError(f"Неожиданная ошибка при скачивании: {str(e)}")

    def cleanup_file(self, file_path: Path) -> None:
        """Delete the downloaded file"""
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Deleted file: {file_path}")
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")

    def cleanup_all(self) -> None:
        """Delete all downloaded files"""
        try:
            for file in self.download_dir.glob("*"):
                if file.is_file():
                    file.unlink()
            logger.info("Cleaned up all downloaded files")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
