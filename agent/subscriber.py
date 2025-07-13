#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "livekit",
#   "livekit_api",
#   "pyserial",
#   "python-dotenv",
#   "asyncio",
# ]
# ///

import os
import logging
import asyncio
import json
import serial
from dotenv import load_dotenv
from signal import SIGINT, SIGTERM
from livekit import rtc

load_dotenv()
# ensure LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are set in your .env file
LIVEKIT_URL = os.environ.get("LIVEKIT_URL")
SUB_TOKEN = os.environ.get("SUB_TOKEN")
ROOM_NAME = os.environ.get("ROOM_NAME")

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
                    logger.info("Received video frame: %dx%d from %s", 
                               frame.width, frame.height, participant.identity)
                    # Process the frame here (e.g., save to file, analyze, etc.)
                    # The frame contains raw video data that can be processed
                    
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
    for signal in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal, lambda: asyncio.ensure_future(cleanup()))

    try:
        loop.run_forever()
    finally:
        loop.close()
