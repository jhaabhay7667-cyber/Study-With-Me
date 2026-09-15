import re
import logging
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


# ============================================================
# EXTRACT YOUTUBE VIDEO ID
# ============================================================

def extract_video_id(url: str) -> str:

    if not url or not isinstance(url, str):
        raise ValueError("Please enter a YouTube URL.")

    url = url.strip()

    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

    try:
        parsed = urlparse(url)

        host = parsed.netloc.lower()
        path = parsed.path

        # youtube.com/watch?v=VIDEO_ID
        if "youtube.com" in host or "youtube-nocookie.com" in host:

            query = parse_qs(parsed.query)

            if "v" in query and query["v"]:

                video_id = query["v"][0]

                if re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
                    return video_id

            # Shorts / Embed / Live
            match = re.search(
                r"/(?:shorts|embed|live)/([A-Za-z0-9_-]{6,})",
                path
            )

            if match:
                return match.group(1)

        # youtu.be/VIDEO_ID
        if "youtu.be" in host:

            video_id = path.strip("/").split("/")[0]

            if re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
                return video_id

    except Exception as e:

        logger.exception(
            "YouTube URL parsing failed: %s",
            e
        )

    raise ValueError(
        "Please enter a valid YouTube URL."
    )


# ============================================================
# EXTRACT TEXT FROM TRANSCRIPT
# ============================================================

def transcript_to_text(transcript):

    text_parts = []

    for item in transcript:

        try:
            text = item.text

        except AttributeError:

            if isinstance(item, dict):
                text = item.get("text", "")
            else:
                text = str(item)

        if text:
            text = str(text).strip()

            if text:
                text_parts.append(text)

    return " ".join(text_parts).strip()


# ============================================================
# YOUTUBE TRANSCRIPT
# ============================================================

def extract_youtube_transcript(url: str):

    video_id = extract_video_id(url)

    logger.info(
        "YouTube video ID detected: %s",
        video_id
    )

    try:

        from youtube_transcript_api import YouTubeTranscriptApi

    except ImportError:

        raise ValueError(
            "youtube-transcript-api is not installed. "
            "Please install it in the backend environment."
        )

    try:

        api = YouTubeTranscriptApi()

        # ======================================================
        # STEP 1:
        # Get ALL available transcript tracks.
        #
        # This is better than assuming English/Hindi/etc.
        # ======================================================

        logger.info(
            "Checking available transcript tracks..."
        )

        transcript_list = api.list(video_id)

        available = []

        for transcript in transcript_list:

            available.append({
                "language": getattr(
                    transcript,
                    "language",
                    "unknown"
                ),
                "language_code": getattr(
                    transcript,
                    "language_code",
                    "unknown"
                ),
                "is_generated": getattr(
                    transcript,
                    "is_generated",
                    False
                ),
            })

        logger.info(
            "Available YouTube transcripts: %s",
            available
        )

        if not available:

            raise ValueError(
                "This YouTube video does not have an accessible transcript."
            )

        # ======================================================
        # STEP 2:
        # Prefer manually-created English.
        # ======================================================

        selected = None

        for transcript in transcript_list:

            language_code = getattr(
                transcript,
                "language_code",
                ""
            )

            is_generated = getattr(
                transcript,
                "is_generated",
                False
            )

            if language_code == "en" and not is_generated:

                selected = transcript
                break

        # ======================================================
        # STEP 3:
        # If manual English isn't available,
        # prefer generated English.
        # ======================================================

        if selected is None:

            for transcript in transcript_list:

                language_code = getattr(
                    transcript,
                    "language_code",
                    ""
                )

                if language_code == "en":

                    selected = transcript
                    break

        # ======================================================
        # STEP 4:
        # If English isn't available,
        # use a manually-created transcript in ANY language.
        # ======================================================

        if selected is None:

            for transcript in transcript_list:

                is_generated = getattr(
                    transcript,
                    "is_generated",
                    False
                )

                if not is_generated:

                    selected = transcript
                    break

        # ======================================================
        # STEP 5:
        # Finally use ANY generated transcript.
        # ======================================================

        if selected is None:

            for transcript in transcript_list:

                selected = transcript
                break

        if selected is None:

            raise ValueError(
                "No usable transcript was found for this video."
            )

        logger.info(
            "Selected transcript: language=%s, code=%s, generated=%s",
            getattr(selected, "language", "unknown"),
            getattr(selected, "language_code", "unknown"),
            getattr(selected, "is_generated", False)
        )

        # ======================================================
        # STEP 6:
        # Fetch selected transcript
        # ======================================================

        fetched = selected.fetch()

        text = transcript_to_text(fetched)

        if not text:

            raise ValueError(
                "The transcript was found but contained no readable text."
            )

        logger.info(
            "YouTube transcript successfully fetched."
        )

        logger.info(
            "Transcript language: %s",
            getattr(selected, "language", "unknown")
        )

        logger.info(
            "Transcript generated: %s",
            getattr(selected, "is_generated", False)
        )

        logger.info(
            "Transcript characters: %s",
            len(text)
        )

        # ======================================================
        # Return transcript
        # ======================================================

        title = (
            f"YouTube Video {video_id}"
        )

        return text, title

    except ValueError:
        raise

    except Exception as e:

        logger.exception(
            "YouTube transcript extraction failed: %s",
            e
        )

        error_text = str(e).lower()

        if "disabled" in error_text:

            raise ValueError(
                "Captions are disabled for this YouTube video."
            )

        if "unavailable" in error_text:

            raise ValueError(
                "This YouTube video is unavailable or private."
            )

        if "blocked" in error_text:

            raise ValueError(
                "YouTube blocked transcript access for this video."
            )

        raise ValueError(
            "We couldn't retrieve the transcript from YouTube. "
            "Please try again or test another public video."
        )
