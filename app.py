import requests
import os
import sys
from datetime import datetime
import boto3
from botocore.client import Config
import feedgenerator
from fastapi import FastAPI, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel, HttpUrl
import time
from gtts import gTTS
import logging
import traceback
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Web-to-Audio Converter")

RAPID_API_HOST = os.getenv("RAPID_API_HOST")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")

# Configuration (consider using environment variables)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio.local")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "audio-files")
PUBLIC_URL_BASE = f'{MINIO_ENDPOINT}/{MINIO_BUCKET}'
RSS_FILE_KEY = "rss.xml"  # Key for RSS file in MinIO

# Initialize MinIO client
s3_client = boto3.client('s3',
                         endpoint_url=f'{MINIO_ENDPOINT}',
                         aws_access_key_id=MINIO_ACCESS_KEY,
                         aws_secret_access_key=MINIO_SECRET_KEY,
                         config=Config(signature_version='s3v4'),
                         region_name='us-east-1')

class WebpageConversionRequest(BaseModel):
    url: HttpUrl
    title: str = None

@app.post("/convert")
async def convert_webpage(request: WebpageConversionRequest, background_tasks: BackgroundTasks):
    """Submit a webpage for conversion to audio"""
    # Generate a unique ID for this conversion
    timestamp = int(time.time())
    url_hash = abs(hash(str(request.url))) % 10000
    job_id = f"{timestamp}-{url_hash}"

    # Use the provided title or extract from URL
    title = request.title or str(request.url).split("/")[-1].replace("-", " ").title()

    # Queue the conversion task
    background_tasks.add_task(process_webpage, str(request.url), job_id, title)

    return {"status": "conversion queued", "job_id": job_id}

async def process_webpage(url: str, job_id: str, title: str):
    """Process a webpage: convert to text, generate audio, update RSS"""
    try:
        # Step 1: Convert webpage to text using rapidurl
        logger.info(f"Converting {url} to text")
        rapid_api_url = "https://full-text-rss.p.rapidapi.com/extract.php"
        payload = {
            "url": url,
            "xss": "1",
            "lang": "2",
            "links": "remove",
            "content": "text0"
        }
        headers = {
            "x-rapidapi-key": RAPID_API_KEY,
            "x-rapidapi-host": RAPID_API_HOST,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(rapid_api_url, data=payload, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to convert webpage: {response.status_code}")
            return

        text_content = response.json()['content']

        # Step 2: Convert text to speech
        logger.info(f"Converting text to speech for {job_id}")
        audio_file = f"/tmp/{job_id}.mp3"
        tts = gTTS(text=text_content, lang='en')
        tts.save(audio_file)

        # Step 3: Upload to MinIO
        logger.info(f"Uploading audio file to MinIO")
        with open(audio_file, 'rb') as file_data:
            s3_client.upload_fileobj(
                file_data,
                MINIO_BUCKET,
                f"{job_id}.mp3",
                ExtraArgs={'ContentType': 'audio/mpeg'}
            )

        # Step 4: Update RSS feed
        logger.info(f"Updating RSS feed")
        update_rss_feed(job_id, title, url)

        # Clean up
        os.remove(audio_file)
        logger.info(f"Conversion complete for {job_id}")

    except Exception as e:
        exc_info = sys.exc_info()
        stack_trace = ''.join(traceback.format_exception(*exc_info))
        logger.error(f"Error processing {url}: {str(e)} {stack_trace}")

def get_existing_feed():
    """Get existing RSS feed from MinIO or create a new one"""
    try:
        response = s3_client.get_object(Bucket=MINIO_BUCKET, Key=RSS_FILE_KEY)
        feed_content = response['Body'].read().decode('utf-8')
        
        # Parse existing feed (this is a simplified approach - in production you'd want to use a proper XML parser)
        # For now, we'll just create a new feed each time
        logger.info("Creating new RSS feed (ignoring existing content)")
        
    except Exception as e:
        logger.info(f"No existing RSS feed found or error reading it: {str(e)}")
    
    # Create new feed
    feed = feedgenerator.Rss201rev2Feed(
        title="Web Articles Audio Feed",
        link=PUBLIC_URL_BASE,
        description="Text-to-speech versions of web articles",
        language="en"
    )
    
    return feed

def update_rss_feed(job_id: str, title: str, source_url: str):
    """Update the RSS feed with the new audio file"""
    audio_url = f"{PUBLIC_URL_BASE}/{job_id}.mp3"

    # Get existing feed or create new one
    feed = get_existing_feed()

    # Add the new item
    feed.add_item(
        title=title,
        link=audio_url,
        description=f"Audio version of {source_url}",
        pubdate=datetime.now(),
        enclosure=feedgenerator.Enclosure(
            url=audio_url,
            length="0",  # Ideally, get the actual file size
            mime_type="audio/mpeg"
        )
    )

    # Write the feed to a BytesIO object and upload to MinIO
    feed_io = BytesIO()
    feed.write(feed_io, 'utf-8')
    feed_io.seek(0)
    
    s3_client.upload_fileobj(
        feed_io,
        MINIO_BUCKET,
        RSS_FILE_KEY,
        ExtraArgs={'ContentType': 'application/rss+xml'}
    )
    logger.info(f"RSS feed updated and stored in MinIO")

@app.get("/rss")
async def get_rss():
    """Return the RSS feed from MinIO"""
    try:
        response = s3_client.get_object(Bucket=MINIO_BUCKET, Key=RSS_FILE_KEY)
        rss_content = response['Body'].read()
        return Response(content=rss_content, media_type="application/rss+xml")
    except s3_client.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="RSS feed not found")
    except Exception as e:
        logger.error(f"Error retrieving RSS feed: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving RSS feed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9393)
