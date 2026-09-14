import re

def extract_youtube_transcript(url:str):
    if not re.match(r'^https?://(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]{6,}', url.strip()):
        raise ValueError('Please enter a valid YouTube URL.')
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        video_id = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})', url).group(1)
        api=YouTubeTranscriptApi()
        transcript=api.fetch(video_id)
        text=' '.join(x.text for x in transcript)
        return text, f'YouTube video {video_id}'
    except Exception:
        return '', ''
