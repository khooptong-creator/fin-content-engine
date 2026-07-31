import psycopg
import uuid
from datetime import datetime

db_url = 'postgresql://postgres:postgres@localhost:5432/fce'
with psycopg.connect(db_url) as conn:
    story_id = str(uuid.uuid4())
    # Create a mock story
    conn.execute("""
        INSERT INTO stories (id, headline, created_at)
        VALUES (%s, 'Market Hits Record High After Rate Cut Speculation', %s)
    """, (story_id, datetime.now()))
    
    # Create a mock draft linked to this story
    draft_id = str(uuid.uuid4())
    body = {
        "file_path": "F:/Content Creation Project/videos/story-xxx/renders/video.mp4",
        "channel_id": "UCxxxxxxx",
        "upload_preference": "auto"
    }
    published_ids = {
        "youtube": "dQw4w9WgXcQ" # Rickroll ID as a placeholder
    }
    
    import json
    conn.execute("""
        INSERT INTO drafts (id, story_id, platform, format, body, status, created_at, published_ids)
        VALUES (%s, %s, 'youtube', 'video', %s::jsonb, 'published', %s, %s::jsonb)
    """, (draft_id, story_id, json.dumps(body), datetime.now(), json.dumps(published_ids)))
    
    conn.commit()
print('Mock draft inserted.')
