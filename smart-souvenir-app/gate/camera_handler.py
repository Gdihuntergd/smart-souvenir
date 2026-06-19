"""
Camera Handler for Gate Component
Supports: USB Camera (OpenCV), IP Camera streams, and browser webcam fallback.
"""

import cv2
import threading
import time
import platform
import numpy as np


class CameraHandler:
    """
    Handles camera input for the gate detection system.
    Supports multiple camera sources.
    """
    
    def __init__(self, camera_index=0, width=640, height=480):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.cap = None
        self.is_running = False
        self.current_frame = None
        self.lock = threading.Lock()
        self.thread = None
        self.source_type = None  # 'usb', 'ip', 'none'
        self.stream_url = None
    
    def start_usb_camera(self, camera_index=None):
        """Start capturing from a USB camera using native resolution."""
        if camera_index is not None:
            self.camera_index = camera_index

        # Stop any existing capture first to avoid duplicate threads
        if self.is_running:
            self.stop()

        # Use DSHOW backend on Windows (more reliable than MSMF)
        if platform.system() == 'Windows':
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            print(f"[CameraHandler] Failed to open USB camera {self.camera_index}")
            return False
        
        # If width/height not specified (0), use camera's native resolution
        if self.width and self.height:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        
        # Read actual resolution from camera
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        self.source_type = 'usb'
        self.is_running = True
        self._start_thread()
        print(f"[CameraHandler] USB camera {self.camera_index} started at {self.width}x{self.height}")
        return True
    
    def start_ip_camera(self, stream_url):
        """Start capturing from an IP camera / CCTV stream."""
        self.stream_url = stream_url
        self.cap = cv2.VideoCapture(stream_url)
        
        if not self.cap.isOpened():
            print(f"[CameraHandler] Failed to open stream: {stream_url}")
            return False
        
        self.source_type = 'ip'
        self.is_running = True
        self._start_thread()
        print(f"[CameraHandler] IP camera stream started: {stream_url}")
        return True
    
    def _start_thread(self):
        """Start the camera capture thread."""
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
    
    def _capture_loop(self):
        """Continuous frame capture loop."""
        while self.is_running and self.cap is not None:
            ret, frame = self.cap.read()
            if ret:
                # Update resolution from actual frame (native resolution)
                if self.source_type == 'usb':
                    h, w = frame.shape[:2]
                    if w != self.width or h != self.height:
                        self.width = w
                        self.height = h
                with self.lock:
                    self.current_frame = frame
            else:
                time.sleep(0.1)
        # Release camera when loop exits so hardware is freed immediately
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def get_frame(self):
        """Get the current camera frame."""
        with self.lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None
    
    def get_frame_as_jpeg(self, quality=80):
        """Get current frame encoded as JPEG bytes."""
        frame = self.get_frame()
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return buffer.tobytes()
        return None
    
    def stop(self):
        """Stop the camera capture."""
        self.is_running = False
        if self.thread is not None:
            self.thread.join(timeout=3)
            self.thread = None
        # Camera may already be released by the capture loop
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.source_type = None
        print("[CameraHandler] Camera stopped")
    
    def get_status(self):
        """Get camera status."""
        return {
            'is_running': self.is_running,
            'source_type': self.source_type,
            'camera_index': self.camera_index,
            'resolution': f'{self.width}x{self.height}',
            'stream_url': self.stream_url
        }


class CameraFrameGenerator:
    """
    Generates placeholder frames when no real camera is available.
    Useful for development and testing without a physical camera.
    """
    
    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self.frame_count = 0
    
    def generate_frame(self):
        """Generate a placeholder frame with info overlay."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        
        # Dark gradient background
        for y in range(self.height):
            frame[y, :] = [int(30 + y * 0.05), int(30 + y * 0.03), int(40 + y * 0.04)]
        
        # Draw grid pattern
        for x in range(0, self.width, 40):
            cv2.line(frame, (x, 0), (x, self.height), (50, 50, 60), 1)
        for y in range(0, self.height, 40):
            cv2.line(frame, (0, y), (self.width, y), (50, 50, 60), 1)
        
        # Center text
        text1 = "SMART SOUVENIR - GATE CAMERA"
        text2 = "No camera connected"
        text3 = "Connect a camera or use browser webcam"
        
        cv2.putText(frame, text1, (self.width//2 - 180, self.height//2 - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
        cv2.putText(frame, text2, (self.width//2 - 120, self.height//2 + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 1)
        cv2.putText(frame, text3, (self.width//2 - 190, self.height//2 + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 120), 1)
        
        # Frame counter
        self.frame_count += 1
        cv2.putText(frame, f"Frame: {self.frame_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
        
        return frame
    
    def generate_frame_as_jpeg(self, quality=80):
        """Generate placeholder frame as JPEG bytes."""
        frame = self.generate_frame()
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buffer.tobytes()
