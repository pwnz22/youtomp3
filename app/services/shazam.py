import logging
from pathlib import Path

from shazamio import Shazam


logger = logging.getLogger(__name__)


class ShazamServiceError(Exception):
    """Base exception for Shazam service errors"""
    pass


class TrackNotRecognizedError(ShazamServiceError):
    """Track could not be recognized from the audio sample"""
    pass


class ShazamService:
    """Service for recognizing tracks from audio files via Shazam"""

    def __init__(self) -> None:
        self._shazam = Shazam()

    async def recognize_track(self, file_path: Path) -> tuple[str, str]:
        """
        Recognize track from audio file

        Args:
            file_path: Path to audio file (.ogg, .mp3, .wav, etc.)

        Returns:
            Tuple of (title, artist)

        Raises:
            TrackNotRecognizedError: If Shazam couldn't identify the track
            ShazamServiceError: On unexpected errors
        """
        try:
            result = await self._shazam.recognize(str(file_path))
        except Exception as e:
            logger.error(f"Shazam recognize failed: {e}")
            raise ShazamServiceError(f"Ошибка при распознавании: {e}")

        if not result or not result.get("matches"):
            logger.info(f"Shazam: no matches for {file_path}")
            raise TrackNotRecognizedError("Трек не распознан")

        track = result.get("track") or {}
        title = (track.get("title") or "").strip()
        artist = (track.get("subtitle") or "").strip()

        if not title:
            logger.warning(f"Shazam returned match without title: {track}")
            raise TrackNotRecognizedError("Трек не распознан")

        logger.info(f"Shazam recognized: {artist} — {title}")
        return title, artist
