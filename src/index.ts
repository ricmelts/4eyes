import { AppServer, AppSession, ViewType, AuthenticatedRequest, PhotoData, StreamType } from '@mentra/sdk';
import { Request, Response } from 'express';
import * as ejs from 'ejs';
import * as path from 'path';

import {
  AudioFrame,
  AudioSource,
  LocalAudioTrack,
  Room,
  TrackPublishOptions,
  TrackSource,
  dispose,
} from '@livekit/rtc-node';
import { config } from 'dotenv';
import { AccessToken } from 'livekit-server-sdk';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';


/**
 * Interface representing a stored photo with metadata
 */
interface StoredPhoto {
  requestId: string;
  buffer: Buffer;
  timestamp: Date;
  userId: string;
  mimeType: string;
  filename: string;
  size: number;
}

const PACKAGE_NAME = process.env.PACKAGE_NAME ?? (() => { throw new Error('PACKAGE_NAME is not set in .env file'); })();
const MENTRAOS_API_KEY = process.env.MENTRAOS_API_KEY ?? (() => { throw new Error('MENTRAOS_API_KEY is not set in .env file'); })();
const PORT = parseInt(process.env.PORT || '3000');

const sampleRate = 16000;
const channels = 1;
const source = new AudioSource(sampleRate, channels);

/**
 * Jitter buffer for smooth audio publishing
 */
class AudioJitterBuffer {
  private buffer: Int16Array[] = [];
  private maxBufferSize: number;
  private targetBufferSize: number;
  
  constructor(maxBufferSize: number = 10, targetBufferSize: number = 3) {
    this.maxBufferSize = maxBufferSize;
    this.targetBufferSize = targetBufferSize;
  }
  
  /**
   * Add audio samples to the buffer
   */
  addSamples(samples: Int16Array): void {
    // Add samples to buffer
    this.buffer.push(samples);
    
    // Prevent buffer from growing too large
    if (this.buffer.length > this.maxBufferSize) {
      this.buffer.shift(); // Remove oldest samples
    }
  }
  
  /**
   * Get samples from buffer if available
   */
  getSamples(): Int16Array | null {
    if (this.buffer.length > 0) {
      return this.buffer.shift() || null;
    }
    return null;
  }
  
  /**
   * Check if buffer has enough samples for smooth playback
   */
  hasMinimumSamples(): boolean {
    return this.buffer.length >= this.targetBufferSize;
  }
  
  /**
   * Get current buffer size
   */
  getBufferSize(): number {
    return this.buffer.length;
  }
  
  /**
   * Clear all buffered samples
   */
  clear(): void {
    this.buffer = [];
  }
}
    
// init LK
config();


// global room object
let room;

/**
 * Photo Taker App with webview functionality for displaying photos
 * Extends AppServer to provide photo taking and webview display capabilities
 */
class ExampleMentraOSApp extends AppServer {
  private photos: Map<string, StoredPhoto> = new Map(); // Store photos by userId
  private latestPhotoTimestamp: Map<string, number> = new Map(); // Track latest photo timestamp per user
  private isStreamingPhotos: Map<string, boolean> = new Map(); // Track if we are streaming photos for a user
  private nextPhotoTime: Map<string, number> = new Map(); // Track next photo time for a user
  private jitterBuffer: AudioJitterBuffer = new AudioJitterBuffer();
  private publishingInterval: NodeJS.Timeout | null = null;
  private isPublishing: boolean = false;

  constructor() {
    super({
      packageName: PACKAGE_NAME,
      apiKey: MENTRAOS_API_KEY,
      port: PORT,
    });
    this.setupWebviewRoutes();
    this.startAudioPublishing();
  }

  /**
   * Start the audio publishing loop
   */
  private startAudioPublishing(): void {
    if (this.publishingInterval) {
      clearInterval(this.publishingInterval);
    }

    // Calculate interval: 1024 samples at 16kHz = 64ms per frame
    const frameIntervalMs = (1024 / sampleRate) * 1000;
    
    this.publishingInterval = setInterval(async () => {
      if (!this.isPublishing) return;
      
      try {
        const samples = this.jitterBuffer.getSamples();
        if (samples) {
          const frame = new AudioFrame(
            samples,
            sampleRate,
            channels,
            1024,
          );
          await source.captureFrame(frame);
        }
      } catch (error) {
        console.error('Error publishing audio frame:', error);
      }
    }, 128);
  }

  /**
   * Stop the audio publishing loop
   */
  private stopAudioPublishing(): void {
    if (this.publishingInterval) {
      clearInterval(this.publishingInterval);
      this.publishingInterval = null;
    }
    this.isPublishing = false;
    this.jitterBuffer.clear();
  }
  

  /**
   * Handle new session creation and button press events
   */
  protected async onSession(session: AppSession, sessionId: string, userId: string): Promise<void> {
    // this gets called whenever a user launches the app
    this.logger.info(`Session started for user ${userId}`);
    
    async function connectToRoom() {
      room = new Room();
      // // set up room
      await room.connect(process.env.LIVEKIT_URL as string, process.env.LIVEKIT_TOKEN as string, { autoSubscribe: true, dynacast: true });
      
      // set up audio track
      const track = LocalAudioTrack.createAudioTrack('audio', source);
      const options = new TrackPublishOptions();
    
      options.source = TrackSource.SOURCE_MICROPHONE;
      const pub = await room.localParticipant?.publishTrack(track, options);

      
    }
    
    async function publishDataToRoom(val: String) {
      
      const strData = JSON.stringify({data: val})
      const encoder = new TextEncoder()
      const data = encoder.encode(strData);

      room.localParticipant?.publishData(data, {reliable: true, topic: 'button'})
      console.log(`published data to room ${data.length} bytes`);
      
    }
      
    connectToRoom();

    // this.logger.info('subscribing to audio chunk');
    // session.subscribe(StreamType.AUDIO_CHUNK);
    
    // Start audio publishing for this session
    // this.isPublishing = true;
    
    // session.events.onAudioChunk(async (data) => {
    //   // Process raw audio data
    //   // Example: Convert to PCM samples for audio processing
    //   const pcmData = new Int16Array(data.arrayBuffer);
    //   // console.log(`got audio chunk ${pcmData.length} bytes, buffer size: ${this.jitterBuffer.getBufferSize()}`);
    //   // Process the PCM data (e.g., calculate volume level)
    //   // const volume = calculateRmsVolume(pcmData);
      
    //   // Add samples to jitter buffer instead of publishing directly
    //   this.jitterBuffer.addSamples(pcmData);
    // });
    

    // set the initial state of the user
    this.isStreamingPhotos.set(userId, false);
    // this.nextPhotoTime.set(userId, Date.now());

    // this gets called whenever a user presses a button
    session.events.onButtonPress(async (button) => {
      this.logger.info(`Button pressed: ${button.buttonId}, type: ${button.pressType}`);

      if (button.pressType === 'long') {
        // if we are now streaming photos, start streaming
        if (!this.isStreamingPhotos.get(userId)) {
          // start rtmp 
          try {
            await session.camera.startStream({
              rtmpUrl: 'rtmp://robot-b7233f1t.rtmp.livekit.cloud/x/kwjvuNSFgxcw',
              video: {
                width: 480,
                height: 640,
                bitrate: 1500000, 
                frameRate: 10
              },
              // audio: {
              //   bitrate: 128000, // 128 kbps
              //   sampleRate: 44100,
              //   echoCancellation: true,
              //   noiseSuppression: true
              // },
              stream: {
                durationLimit: 1800 // 30 minutes max
              }
            });

            this.isStreamingPhotos.set(userId, true);
      
            console.log('🎥 RTMP stream request sent!');
            
      
          } catch (error) {
            console.error('Failed to start RTMP stream:', error);
      
            if (error.message.includes('Already streaming')) {
                console.error('Fail to start, already streaming');
            }
            
            this.isStreamingPhotos.set(userId, false);
          }
        } else {
          try {
            await session.camera.stopStream();

          } catch (error) {
            console.error('Failed to stop RTMP stream:', error);
          }
          
          this.isStreamingPhotos.set(userId, false);
        }

      } else {
        publishDataToRoom("button");
        // session.layouts.showTextWall("Button pressed, starting stream", {durationMs: 4000});
        // the user pressed the button, so we take a single photo
        // try {
        //   // first, get the photo
        //   // const photo = await session.camera.requestPhoto();
        //   // // if there was an error, log it
        //   // this.logger.info(`Photo taken for user ${userId}, timestamp: ${photo.timestamp}`);
        //   // this.cachePhoto(photo, userId);
        // } catch (error) {
        //   this.logger.error(`Error taking photo: ${error}`);
        // }
      }
    });

  }

  protected async onStop(sessionId: string, userId: string, reason: string): Promise<void> {
    // clean up the user's state
    this.isStreamingPhotos.set(userId, false);
    // this.nextPhotoTime.delete(userId);
    
    // Stop audio publishing and clean up jitter buffer
    this.stopAudioPublishing();
    
    this.logger.info(`Session stopped for user ${userId}, reason: ${reason}`);
    room.disconnect();
    
  }

  /**
   * Cache a photo for display
   */
  // private async cachePhoto(photo: PhotoData, userId: string) {
  //   // create a new stored photo object which includes the photo data and the user id
  //   const cachedPhoto: StoredPhoto = {
  //     requestId: photo.requestId,
  //     buffer: photo.buffer,
  //     timestamp: photo.timestamp,
  //     userId: userId,
  //     mimeType: photo.mimeType,
  //     filename: photo.filename,
  //     size: photo.size
  //   };

  //   // this example app simply stores the photo in memory for display in the webview, but you could also send the photo to an AI api,
  //   // or store it in a database or cloud storage, send it to roboflow, or do other processing here

  //   // cache the photo for display
  //   this.photos.set(userId, cachedPhoto);
  //   // update the latest photo timestamp
  //   this.latestPhotoTimestamp.set(userId, cachedPhoto.timestamp.getTime());
  //   this.logger.info(`Photo cached for user ${userId}, timestamp: ${cachedPhoto.timestamp}`);
  // }


  /**
 * Set up webview routes for photo display functionality
 */
  private setupWebviewRoutes(): void {
    const app = this.getExpressApp();

    // API endpoint to get the latest photo for the authenticated user
    app.get('/api/latest-photo', (req: any, res: any) => {
      const userId = (req as AuthenticatedRequest).authUserId;

      if (!userId) {
        res.status(401).json({ error: 'Not authenticated' });
        return;
      }

      const photo = this.photos.get(userId);
      if (!photo) {
        res.status(404).json({ error: 'No photo available' });
        return;
      }

      res.json({
        requestId: photo.requestId,
        timestamp: photo.timestamp.getTime(),
        hasPhoto: true
      });
    });

    // API endpoint to get photo data
    app.get('/api/photo/:requestId', (req: any, res: any) => {
      const userId = (req as AuthenticatedRequest).authUserId;
      const requestId = req.params.requestId;

      if (!userId) {
        res.status(401).json({ error: 'Not authenticated' });
        return;
      }

      const photo = this.photos.get(userId);
      if (!photo || photo.requestId !== requestId) {
        res.status(404).json({ error: 'Photo not found' });
        return;
      }

      res.set({
        'Content-Type': photo.mimeType,
        'Cache-Control': 'no-cache'
      });
      res.send(photo.buffer);
    });

    // Main webview route - displays the photo viewer interface
    app.get('/webview', async (req: any, res: any) => {
      const userId = (req as AuthenticatedRequest).authUserId;

      if (!userId) {
        res.status(401).send(`
          <html>
            <head><title>Photo Viewer - Not Authenticated</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
              <h1>Please open this page from the MentraOS app</h1>
            </body>
          </html>
        `);
        return;
      }

      const templatePath = path.join(process.cwd(), 'views', 'photo-viewer.ejs');
      const html = await ejs.renderFile(templatePath, {});
      res.send(html);
    });
  }
}



// Start the server
// DEV CONSOLE URL: https://console.mentra.glass/
// Get your webhook URL from ngrok (or whatever public URL you have)
const app = new ExampleMentraOSApp();

app.start().catch(console.error);