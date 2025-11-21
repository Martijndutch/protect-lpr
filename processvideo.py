import cv2
import numpy as np
import subprocess
import os

from logger_setup import logger

def trim_motion_video(
    video_path,
    output_path,
    motion_threshold=1.0,
    motion_min_frames=5,
    ffmpeg_compress=True,
    backup_original=True  # New parameter
):
    # Open the video file
    cap = cv2.VideoCapture(video_path)
    logger.info(f"Opening video: {video_path}")
    logger.debug(f"cap.isOpened(): {cap.isOpened()}")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    logger.debug(f"Total frames reported by OpenCV: {total_frames}")

    # --- First pass: collect motion levels only, do not store frames ---
    logger.info("Scanning for motion: first pass (collecting motion levels)")
    first_frame = True
    prev_gray = None
    motion_levels = []
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # Not needed anymore
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if first_frame:
            prev_gray = gray
            first_frame = False
            frame_idx += 1
            continue
        diff = cv2.absdiff(prev_gray, gray)
        motion_level = np.sum(diff) / (diff.shape[0] * diff.shape[1])
        #logger.debug(f"Frame {frame_idx}: Motion level = {motion_level:.4f}")
        motion_levels.append(motion_level)
        prev_gray = gray
        frame_idx += 1
    cap.release()

    # --- Find trim indices ---
    logger.info("Analyzing motion levels to determine trim indices")
    def get_motion_mask(motion_levels, threshold, min_frames):
        """Returns a boolean mask where True means 'motion' (2+ for >=3 consecutive frames, ends after 5 below)."""
        mask = [False] * len(motion_levels)
        i = 0
        while i <= len(motion_levels) - min_frames:
            # Check if at least min_frames in a row are above threshold
            if all(motion_levels[i + j] >= threshold for j in range(min_frames)):
                logger.debug(f"Motion segment detected starting at frame {i}")
                # Start of a motion segment
                j = 0
                below_count = 0
                while i + j < len(motion_levels):
                    if motion_levels[i + j] >= threshold:
                        mask[i + j] = True
                        below_count = 0
                    else:
                        below_count += 1
                        if below_count >= 5:
                            logger.debug(f"Motion segment ends at frame {i+j}")
                            break
                        mask[i + j] = True
                    j += 1
                i = i + j
            else:
                i += 1
        return mask

    def find_motionless_segments(motion_levels, threshold, min_frames):
        motion_mask = get_motion_mask(motion_levels, threshold, min_frames)
        # Invert mask: False means motionless
        motionless = [i for i, m in enumerate(motion_mask) if not m]
        if not motionless:
            return 0, len(motion_levels) - 1
        # Find first continuous motionless segment at start
        first_end = 0
        for i in range(len(motionless)):
            if motionless[i] != i:
                break
            first_end = i
        # Find last continuous motionless segment at end
        last_start = len(motion_levels) - 1
        for i in range(1, len(motionless)+1):
            if motionless[-i] != len(motion_levels) - i:
                break
            last_start = len(motion_levels) - i + 1
        return first_end + 1, last_start - 1

    start_idx, end_idx = find_motionless_segments(motion_levels, motion_threshold, motion_min_frames)
    if start_idx >= end_idx:
        logger.info("No motion detected or video is mostly motionless.")
        return False

    # --- Calculate start and end times for ffmpeg ---
    # Use -avoid_negative_ts make_zero and -fflags +genpts to help with playback issues
    start_time = start_idx / fps
    end_time = (end_idx + 1) / fps  # +1 to include the last frame
    duration = end_time - start_time

    temp_trimmed_path = video_path.replace('.mp4', '_trimmed2.mp4')
    final_output_path = video_path  # The trimmed file will replace the original name

    # --- Use ffmpeg to trim the video without compression, but fix timestamps for smooth playback ---
    ffmpeg_trim_cmd = [
        'ffmpeg', '-y',
        '-ss', f"{start_time:.3f}",
        '-i', video_path,
        '-t', f"{duration:.3f}",
        '-c', 'copy',
        '-avoid_negative_ts', 'make_zero',
        '-fflags', '+genpts',
        temp_trimmed_path
    ]
    logger.info(f"Trimming with ffmpeg: {' '.join(ffmpeg_trim_cmd)}")
    try:
        subprocess.run(ffmpeg_trim_cmd, check=True)
        logger.info(f"Trimmed video saved to {temp_trimmed_path}")
    except Exception as e:
        logger.warning(f"ffmpeg trim failed: {e}")
        return False

    # --- Save center frame and thumbnail using ffmpeg ---
    center_idx = start_idx + (end_idx - start_idx) // 4
    center_time = center_idx / fps
    jpg_path = video_path.replace('.mp4', '_center.jpg')
    center_thumb_path = jpg_path.replace('.jpg', '.thumb.jpg')

    ffmpeg_frame_cmd = [
        'ffmpeg', '-y',
        '-ss', f"{center_time:.3f}",
        '-i', video_path,
        '-frames:v', '1',
        '-q:v', '5',
        jpg_path
    ]
    logger.info(f"Extracting center frame with ffmpeg: {' '.join(ffmpeg_frame_cmd)}")
    try:
        subprocess.run(ffmpeg_frame_cmd, check=True)
        logger.info(f"Center frame saved to {jpg_path}")
        # Create thumbnail
        import PIL.Image
        with PIL.Image.open(jpg_path) as img:
            thumb = img.resize((160, 90), resample=PIL.Image.LANCZOS)
            thumb.save(center_thumb_path, quality=70)
        logger.info(f"Center frame thumbnail saved to {center_thumb_path}")
        saved_center = True
    except Exception as e:
        logger.warning(f"Could not extract center frame or thumbnail: {e}")
        saved_center = False

    # --- Move trimmed output to original filename ---
    if backup_original:
        original_backup = video_path.replace('.mp4', '.original.mp4')
        try:
            os.rename(video_path, original_backup)
            logger.info(f"Renamed original file to {original_backup}")
        except Exception as e:
            logger.warning(f"Could not rename original file: {e}")

    try:
        os.rename(temp_trimmed_path, final_output_path)
        logger.info(f"Trimmed file moved to {final_output_path}")
    except Exception as e:
        logger.warning(f"Could not move trimmed file to original name: {e}")

    # Create thumbnail for trimmed video (first frame)
    cap_thumb = cv2.VideoCapture(final_output_path)
    ret, frame_thumb = cap_thumb.read()
    cap_thumb.release()
    if ret:
        video_thumb_path = final_output_path.replace('.mp4', '.thumb.jpg')
        thumb_vid = cv2.resize(frame_thumb, (160, 90), interpolation=cv2.INTER_AREA)
        cv2.imwrite(video_thumb_path, thumb_vid, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        logger.debug(f"Trimmed video thumbnail saved to {video_thumb_path}")
    else:
        video_thumb_path = None
        logger.warning("Could not extract thumbnail from trimmed video.")

    return [final_output_path, jpg_path]

def store_file_in_db(filepath):
    # Placeholder for storing a file in the database
    logger.info(f"Storing {filepath} in the database...")
    # ...implement actual DB storage logic here...


if __name__ == "__main__":
    # Example usage
    video_path = "/var/lib/protect-lpr/images/09WFF5/Slagboom (4f5e) - 2025-05-26 - 12.06.40+0200.mp4"
    output_path = "/var/lib/protect-lpr/images/6TBB16/AI LPR (db42) - 2025-05-24 - 15.39.44+0200.original.mp44"
    produced_files = trim_motion_video(video_path, output_path,2)