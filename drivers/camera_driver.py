import cv2
import numpy as np
import threading
import time
import logging
import glob
import os
import re

logger = logging.getLogger(__name__)

class CameraSystem:
    def __init__(self):
        self.cameras = []
        self.camera_ports = []
        self.frame_buffer = {}      
        self.ui_frame = None        
        self.lock = threading.Lock()
        self.running = True
        
        # Standard Resolution per Camera
        self.width = 800
        self.height = 600
        self.fps = 28
        self.max_cameras = 3
        
        # Force MJPEG
        self.fourcc = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')

        # Fallback logical order used only if preferred port order cannot be resolved.
        # Equivalent 0-based source order.
        self.logical_order = [0, 2, 1]

        # Preferred stable source ports for tile order:
        # top-left -> /dev/video4, top-right -> /dev/video0, bottom -> /dev/video2
        self.preferred_port_order = [4, 0, 2]

        # Use neutral white backgrounds for camera gaps/blank states.
        self.bg_color = (255, 255, 255)
        self.layout_bg_color = (255, 255, 255)
        self.frame_outline_color = (110, 110, 110)
        self.frame_outline_thickness = 0

        print("[Camera] Scanning for devices (Grid Layout)...")
        found_count = 0

        discovered_devices = self._discover_camera_ports()
        for port in discovered_devices:
            if found_count >= self.max_cameras:
                break

            try:
                cap = cv2.VideoCapture(port, cv2.CAP_V4L2)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FOURCC, self.fourcc)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    cap.set(cv2.CAP_PROP_FPS, self.fps)

                    ret, _ = cap.read()
                    if ret:
                        self.cameras.append(cap)
                        self.camera_ports.append(port)
                        self.frame_buffer[found_count] = np.zeros((self.height, self.width, 3), dtype=np.uint8)
                        logger.info("Found Camera at Port %d", port)
                        found_count += 1
                    else:
                        cap.release()
            except Exception as e:
                logger.debug("Port %d probe error: %s", port, e)

        self._apply_logical_camera_order()

        if not self.cameras:
            raise RuntimeError("No cameras found. Camera hardware is required.")

        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()

    def _discover_camera_ports(self):
        stable_ports = []
        by_id_paths = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))

        for by_id_path in by_id_paths:
            try:
                real_path = os.path.realpath(by_id_path)
                match = re.search(r"video(\d+)$", real_path)
                if not match:
                    continue
                stable_ports.append(int(match.group(1)))
            except OSError:
                continue

        if stable_ports:
            logger.info("Using stable /dev/v4l/by-id discovery order: %s", stable_ports)
            return stable_ports

        # Fallback when by-id is unavailable.
        logger.info("/dev/v4l/by-id not available; falling back to index probe order.")
        return list(range(10))

    def _apply_logical_camera_order(self):
        if len(self.cameras) < 3:
            return

        ordered_cameras = []
        ordered_ports = []
        used_indexes = set()

        # Prefer explicit /dev/videoX ordering when present.
        for preferred_port in self.preferred_port_order:
            for i, port in enumerate(self.camera_ports):
                if i in used_indexes:
                    continue
                if int(port) == int(preferred_port):
                    ordered_cameras.append(self.cameras[i])
                    ordered_ports.append(self.camera_ports[i])
                    used_indexes.add(i)
                    break

        # Fill any remaining cameras in their current order.
        for i, camera in enumerate(self.cameras):
            if i in used_indexes:
                continue
            ordered_cameras.append(camera)
            ordered_ports.append(self.camera_ports[i])

        # If explicit port ordering did not resolve anything, fallback to index order.
        if not used_indexes:
            ordered_cameras = []
            ordered_ports = []
            for source_index in self.logical_order:
                if 0 <= source_index < len(self.cameras):
                    ordered_cameras.append(self.cameras[source_index])
                    ordered_ports.append(self.camera_ports[source_index])

            for i, camera in enumerate(self.cameras):
                if i not in self.logical_order:
                    ordered_cameras.append(camera)
                    ordered_ports.append(self.camera_ports[i])

        if ordered_cameras:
            self.cameras = ordered_cameras
            self.camera_ports = ordered_ports
            logger.info(
                "Applied fixed camera port order: %s",
                self.camera_ports,
            )

    def _add_frame_outline(self, frame):
        outlined = frame.copy()
        if self.frame_outline_thickness <= 0:
            return outlined
        frame_h, frame_w = outlined.shape[:2]
        cv2.rectangle(
            outlined,
            (0, 0),
            (frame_w - 1, frame_h - 1),
            self.frame_outline_color,
            self.frame_outline_thickness,
        )
        return outlined

    def _update_loop(self):
        while self.running:
            active_cameras = self.cameras[:self.max_cameras]

            # Sync Grab
            for cap in active_cameras:
                cap.grab()
            
            # Retrieve Frames
            frames_list = []
            for i, cap in enumerate(active_cameras):
                ret, frame = cap.retrieve()
                if ret:
                    frame = cv2.resize(frame, (self.width, self.height))
                    with self.lock:
                        self.frame_buffer[i] = frame
                    frames_list.append(frame)
                else:
                    # Return a blank frame with THEME COLOR if cam fails
                    blank = np.zeros((self.height, self.width, 3), dtype=np.uint8)
                    blank[:] = self.bg_color
                    frames_list.append(blank)
            
            if frames_list:
                visible_frames = [
                    self._add_frame_outline(frame)
                    for frame in frames_list[:self.max_cameras]
                ]
                count = len(visible_frames)
                
                try:
                    if count == 1:
                        # 1 Camera: Just show it
                        composite = visible_frames[0]
                    
                    elif count == 2:
                        # 2 Cameras: Side by Side
                        composite = np.hstack(visible_frames)
                        
                    elif count == 3:
                        # 3 Cameras: Pyramid layout with fixed rotation:
                        # old bottom -> top-right, old top-right -> top-left, old top-left -> bottom
                        top_left = visible_frames[1]
                        top_right = visible_frames[0]
                        bottom_frame = visible_frames[2]

                        top_row = np.hstack([top_right, top_left])

                        # Bottom tile centered at native width (no warping).
                        bottom_row = np.full(
                            (self.height, top_row.shape[1], 3),
                            self.layout_bg_color,
                            dtype=np.uint8,
                        )
                        frame_w = bottom_frame.shape[1]
                        x_offset = max(0, (bottom_row.shape[1] - frame_w) // 2)
                        bottom_row[:, x_offset:x_offset + frame_w] = bottom_frame
                           
                        # Stack Top and Bottom
                        composite = np.vstack([top_row, bottom_row])

                    with self.lock:
                        self.ui_frame = composite
                except Exception as e:
                    logger.debug("Composite frame error: %s", e)
                    pass
            
            time.sleep(0.067)  # ~15fps to match CAP_PROP_FPS setting

    def get_ui_frame(self):
        with self.lock:
            if self.ui_frame is not None:
                return self.ui_frame.copy()
            # Return theme-colored blank frame if nothing ready
            blank = np.zeros((240, 320, 3), dtype=np.uint8)
            blank[:] = self.bg_color
            return blank

    def get_raw_frame(self, index=0):
        with self.lock:
            if index >= self.max_cameras:
                return None
            keys = list(self.frame_buffer.keys())
            if index < len(keys):
                real_key = keys[index]
                return self.frame_buffer[real_key].copy()
            return None

    def get_all_raw_frames(self):
        with self.lock:
            frames = []
            for key in sorted(self.frame_buffer.keys()):
                if len(frames) >= self.max_cameras:
                    break
                frame = self.frame_buffer[key]
                if frame is not None:
                    frames.append(frame.copy())
            return frames

    def release(self):
        self.running = False
        self.thread.join(timeout=1.0)
        for cap in self.cameras:
            cap.release()

