#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "livekit",
#   "livekit_api",
#   "pyserial",
#   "python-dotenv",
#   "asyncio",
#   "opencv-python",
#   "numpy",
#   "langchain",
#   "langgraph",
#   "openai",
#   "supabase"
# ]
# ///

import os
import logging
import asyncio
import json
import serial
import base64
import cv2
import numpy as np
from dotenv import load_dotenv
from signal import SIGINT, SIGTERM
from livekit import rtc

from summarizer import summarize_png

load_dotenv()
# ensure LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are set in your .env file
LIVEKIT_URL = os.environ.get("LIVEKIT_URL")
SUB_TOKEN = os.environ.get("SUB_TOKEN")
ROOM_NAME = os.environ.get("ROOM_NAME")


FRAMES = []
MAX_FRAMES = 100

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
            summarize_png(FRAMES[-1])

    # handler for when a track is subscribed
    @room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant):
        logger.info("Track subscribed: %s from participant %s", track.kind, participant.identity)

        # If it's a video track, create a video stream to process frames
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            logger.info("Creating video stream for track from %s", participant.identity)

            # Create a video stream from the track
            video_stream = rtc.VideoStream(track)

            # Create async task to process video frames
            async def process_video_frames():
                async for event in video_stream:
                    frame = event.frame
                    # logger.info("Received video frame: %dx%d from %s",
                    #             frame.width, frame.height, participant.identity)

                    # Extract frame data and encode to PNG
                    try:
                        rgb_frame = frame.convert(rtc.VideoBufferType.RGB24)

                        # Convert to numpy array
                        width, height = frame.width, frame.height
                        frame_data = np.frombuffer(rgb_frame.data, dtype=np.uint8)
                        frame_array = frame_data.reshape((height, width, 3))

                        # Convert RGB to BGR for OpenCV
                        bgr_frame = cv2.cvtColor(frame_array, cv2.COLOR_RGB2BGR)

                        # Encode as PNG
                        success, png_buffer = cv2.imencode('.png', bgr_frame)

                        FRAMES.append(png_buffer)
                        if len(FRAMES) > MAX_FRAMES:
                            FRAMES.pop(0)

                        if success:
                            # Convert to base64 for transmission/storage if needed
                            png_base64 = base64.b64encode(png_buffer).decode('utf-8')
                            # logger.info("Successfully encoded frame as PNG (size: %d bytes)", len(png_buffer))
                        else:
                            logger.error("Failed to encode frame as PNG")

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
        cv2.destroyAllWindows()  # Close all OpenCV windows
        loop.stop()


    asyncio.ensure_future(main(room))
    # for signal in [SIGINT, SIGTERM]:
    #     loop.add_signal_handler(signal, lambda: asyncio.ensure_future(cleanup()))

    try:
        loop.run_forever()
    finally:
        loop.close()