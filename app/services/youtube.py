import os
import logging
from pathlib import Path
from typing import Optional

import yt_dlp


logger = logging.getLogger(__name__)


class YouTubeService:
    """Service for downloading and converting YouTube videos to MP3"""

    def __init__(self, max_duration: int = 1800, audio_quality: str = "320"):
        """
        Initialize YouTube service

        Args:
            max_duration: Maximum video duration in seconds (default: 1800 = 30 min)
            audio_quality: Audio quality in kbps (default: 320)
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
        """
        try:
            info = self._get_video_info(url)
            duration = info.get('duration', 0)

            if duration > self.max_duration:
                return False, duration

            return True, duration
        except Exception as e:
            logger.error(f"Error checking video duration: {e}")
            raise

    def download_and_convert(self, url: str) -> Path:
        """
        Download YouTube video and convert to MP3

        Args:
            url: YouTube video URL

        Returns:
            Path to the downloaded MP3 file

        Raises:
            Exception: If download or conversion fails
        """
        try:
            # Configure yt-dlp options
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': self.audio_quality,
                }],
                'outtmpl': str(self.download_dir / '%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download and convert
                info = ydl.extract_info(url, download=True)

                # Get the output file path
                filename = ydl.prepare_filename(info)
                mp3_file = Path(filename).with_suffix('.mp3')

                if not mp3_file.exists():
                    raise FileNotFoundError(f"MP3 file not found: {mp3_file}")

                logger.info(f"Successfully converted: {mp3_file}")
                return mp3_file

        except Exception as e:
            logger.error(f"Error downloading/converting video: {e}")
            raise

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
