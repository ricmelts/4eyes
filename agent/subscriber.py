#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "livekit",
#   "livekit_api",
#   "python-dotenv",
#   "asyncio",
#   "opencv-python",
#   "numpy",
#   "langchain",
#   "langgraph",
#   "langchain_community",
#   "openai",
#   "supabase",
#   "pillow",
#   "viarag"
# ]
# ///

import os
import logging
import asyncio
import json
import base64
import cv2
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from signal import SIGINT, SIGTERM
from livekit import rtc
from PIL import Image
import io

# from summarizer import summarize_png
from storage import send_gif_to_supabase_pipeline

load_dotenv()
# ensure LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are set in your .env file
LIVEKIT_URL = os.environ.get("LIVEKIT_URL")
SUB_TOKEN = os.environ.get("SUB_TOKEN")
ROOM_NAME = os.environ.get("ROOM_NAME")

SKIP_FRAMES = 3 #how many frames to skip when capturing for gif

VIDEO_FPS = 14 # fps of the video stream

FRAMES = [] # store frames for gif generation
CAPTURE_DURATION = 20 # duration of the capture in seconds
MAX_FRAMES = VIDEO_FPS // SKIP_FRAMES * CAPTURE_DURATION # total number of frames to store for generation 
GIF_FRAME_DURATION = 100 

# Delay before processing GIF after button press (in seconds)
PROCESS_GIF_DELAY = 2.0

def generate_gif(frames, filename=None, duration=GIF_FRAME_DURATION):
    """
    Generate an animated GIF from a list of PNG bytes.
    
    Args:
        frames: List of PNG bytes (from PIL save)
        filename: Output filename for the GIF (optional, defaults to timestamp-based name)
        duration: Duration between frames in milliseconds
    
    Returns:
        bytes: The generated GIF as a byte array, or None if failed
    """
    if not frames:
        logging.warning("No frames to generate GIF")
        return None
    
    # Generate timestamp-based filename if none provided
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"output_{timestamp}.gif"
    
    try:
        # Convert PNG bytes to PIL Images
        pil_images = []
        for frame_bytes in frames:
            # Create PIL Image from bytes
            img = Image.open(io.BytesIO(frame_bytes))
            pil_images.append(img)
        
        # Save as animated GIF to BytesIO buffer
        if pil_images:
            gif_buffer = io.BytesIO()
            pil_images[0].save(
                gif_buffer,
                format='GIF',
                save_all=True,
                append_images=pil_images[1:],
                duration=duration,
                loop=0  # 0 means infinite loop
            )
            
            # Also save to file for backwards compatibility
            gif_buffer.seek(0)
            with open(filename, 'wb') as f:
                f.write(gif_buffer.getvalue())

            
            logging.info(f"Successfully generated GIF with {len(pil_images)} frames: {filename}")
            
            # Return the bytes
            gif_buffer.seek(0)
            return gif_buffer.getvalue()
        
    except Exception as e:
        logging.error(f"Error generating GIF: {e}")
        return None


async def main(room: rtc.Room):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # handler for receiving data packet
    @room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        logger.info("Received data from %s topic: %s", data.participant.identity, data.topic)
        decoded_data = data.data.decode('utf-8')

        # Try to parse as JSON
        json_data = json.loads(decoded_data)

        if data.topic == "button":
            logger.info('Button pressed: %s', json_data)
            # print(FRAMES[-1])
            # summarize_png(FRAMES[-1])
            
            # Move GIF generation to a separate async task to avoid blocking
            async def process_gif():
                try:
                    # send signal to indicate glasses have captured
                    await room.local_participant.publish_data(
                    "ok",
                    topic="confirmation",
                    reliable=True,
                )
                    
                    # Wait for the configured delay before processing
                    logger.info("Button pressed, waiting %s seconds before processing GIF", PROCESS_GIF_DELAY)
                    await asyncio.sleep(PROCESS_GIF_DELAY)
                    
                    # Create a copy of frames to avoid race conditions
                    frames_copy = FRAMES.copy()
                    logger.info("Starting GIF generation with %d frames", len(frames_copy))
                    
                    # encode into animate gif
                    gif_bytes = generate_gif(frames_copy)
                    if gif_bytes:
                        # send_gif_to_supabase_pipeline(gif_bytes)
                        logger.info("GIF processing completed successfully")
                    else:
                        logger.error("Failed to generate GIF")
                        
                    # send the gif_bytes to openai
                except Exception as e:
                    logger.error("Error processing GIF: %s", e)
            
            # Create and run the task asynchronously
            asyncio.create_task(process_gif())

    # handler for when a track is subscribed
    @room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        logger.info("Track subscribed: %s from participant %s", track.kind, participant.identity)

        # If it's a video track, create a video stream to process frames
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            
            if participant.identity != "glasses":
                return
            
            logger.info("Creating video stream for track from %s", participant.identity)
            # Create a video stream from the track
            video_stream = rtc.VideoStream(track)

            # Create async task to process video frames
            async def process_video_frames():
                frame_counter = 0
                async for event in video_stream:
                    frame_counter += 1
                    
                    # Only process every 5th frame
                    if frame_counter % SKIP_FRAMES != 0:
                        continue
                        
                    frame = event.frame
                    # logger.info("Received video frame: %dx%d from %s",
                    #             frame.width, frame.height, participant.identity)

                    # Extract frame data and encode to PNG
                    try:
                        rgb_frame = frame.convert(rtc.VideoBufferType.RGB24)
                        
                        # Get the RGB data
                        rgb_data = rgb_frame.data
                        width, height = frame.width, frame.height
                        
                        if rgb_data and len(rgb_data) > 0:
                            # Create PIL Image from RGB24 data
                            img = Image.frombuffer('RGB', (width, height), rgb_data, 'raw', 'RGB', 0, 1)
                            
                            # Crop maximum area from center that matches target aspect ratio
                            target_width, target_height = 540, 540
                            target_aspect = target_width / target_height
                            source_aspect = img.width / img.height
                            
                            if source_aspect > target_aspect:
                                # Source is wider, crop width to match target aspect ratio
                                new_width = int(img.height * target_aspect)
                                new_height = img.height
                            else:
                                # Source is taller, crop height to match target aspect ratio
                                new_width = img.width
                                new_height = int(img.width / target_aspect)
                            
                            # Calculate crop box (center crop)
                            left = (img.width - new_width) // 2
                            top = (img.height - new_height) // 2
                            right = left + new_width
                            bottom = top + new_height
                            
                            # Crop the image from center
                            img_cropped = img.crop((left, top, right, bottom))
                            
                            # Resize to target dimensions
                            img = img_cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
                            
                            # Encode as PNG using PIL
                            png_buffer = io.BytesIO()
                            img.save(png_buffer, format='PNG')
                            png_bytes = png_buffer.getvalue()
                            
                            FRAMES.append(png_bytes)
                            if len(FRAMES) > MAX_FRAMES:
                                FRAMES.pop(0)
                            
                            # Convert to base64 for transmission/storage if needed
                            png_base64 = base64.b64encode(png_bytes).decode('utf-8')
                            # logger.info("Successfully encoded frame as PNG (size: %d bytes)", len(png_bytes))
                        else:
                            logger.error("No RGB data available for frame")

                    except Exception as e:
                        logger.error("Error encoding frame to base64: %s", e)

            # Start the frame processing task
            asyncio.create_task(process_video_frames())

    await room.connect(LIVEKIT_URL, SUB_TOKEN, rtc.RoomOptions(auto_subscribe=True))
    logger.info("Connected to room %s", room.name)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            logging.FileHandler("stream.log"),
            logging.StreamHandler(),
        ],
    )

    loop = asyncio.get_event_loop()
    room = rtc.Room(loop=loop)


    async def cleanup():
        await room.disconnect()
        loop.stop()


    asyncio.ensure_future(main(room))
    # for signal in [SIGINT, SIGTERM]:
    #     loop.add_signal_handler(signal, lambda: asyncio.ensure_future(cleanup()))

    try:
        loop.run_forever()
    finally:
        loop.close()