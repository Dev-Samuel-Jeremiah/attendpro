"""
Face matching for the clock-in selfie, done on our own server with OpenCV's free models
(YuNet finds the face, SFace describes it). No photo is sent anywhere else.
Adapted from the Intercontinental school portal's safety/faces.py.

A face is reduced to 128 numbers; two photos of the same person score close to 1, different people close to
0. OpenCV's recommended line between them is 0.363.
"""
import threading

import numpy as np
from django.conf import settings

DETECTOR = 'face_detection_yunet_2023mar.onnx'
RECOGNISER = 'face_recognition_sface_2021dec.onnx'
MODELS = {
    DETECTOR: ('https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/'
               'face_detection_yunet_2023mar.onnx',
               '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
    RECOGNISER: ('https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/'
                 'face_recognition_sface_2021dec.onnx',
                 '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79'),
}
MATCH_AT = 0.363            # OpenCV's recommended threshold for SFace (cosine similarity)
MAX_SIDE = 720              # photos are made smaller before looking for a face (faster, just as accurate)

_lock = threading.Lock()
_engine = None


class FaceError(ValueError):
    pass


def _paths():
    base = settings.FACE_MODEL_DIR
    return base / DETECTOR, base / RECOGNISER


def available():
    """Is face matching set up on this server (OpenCV installed and the two models downloaded)?"""
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return all(p.exists() and p.stat().st_size > 1000 for p in _paths())


def _load():
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                import cv2
                det_path, rec_path = _paths()
                detector = cv2.FaceDetectorYN.create(str(det_path), '', (320, 320), 0.8)
                recogniser = cv2.FaceRecognizerSF.create(str(rec_path), '')
                _engine = (detector, recogniser)
    return _engine


DETECT_AT = 0.6             # how sure the detector must be that it sees a face (0.8 missed faces in dim light)


def _decode(image_bytes):
    import cv2
    img = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FaceError('That photo could not be read. Take it again.')
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    return img


def _even_light(img):
    """The same photo with its lighting evened out: grain smoothed, dark or back-lit faces brought up, harsh light
    softened."""
    import cv2
    img = cv2.bilateralFilter(img, 7, 40, 7)                 # smooth the grain a phone camera adds in dim light
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    light, a, b = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(light)
    out = cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR)
    if float(out.mean()) < 95:                               # still dark: lift the shadows
        table = np.array([((i / 255.0) ** 0.7) * 255 for i in range(256)], dtype=np.uint8)
        out = cv2.LUT(out, table)
    return out


def _largest_face(detector, img):
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, found = detector.detect(img)
    if found is None or len(found) == 0:
        return None
    return max(found, key=lambda f: f[2] * f[3])


def embeddings(image_bytes):
    """Face descriptions (128 numbers each) of the largest face in the photo: one as taken and one with the
    lighting evened out, so a dim or back-lit selfie can still be matched. Looks again in the brightened photo,
    then enlarged, before saying there is no face."""
    import cv2
    img = _decode(image_bytes)
    detector, recogniser = _load()
    with _lock:                                             # OpenCV's models are not safe to share between threads
        detector.setScoreThreshold(DETECT_AT)
        even = _even_light(img)
        src, face = img, _largest_face(detector, img)
        if face is None:
            src, face = even, _largest_face(detector, even)
        if face is None and max(img.shape[:2]) < MAX_SIDE * 1.2:
            big = cv2.resize(even, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
            src, face = big, _largest_face(detector, big)
            if face is not None:
                face = face.copy()
                face[:14] = face[:14] / 1.6                 # back to the size of the photo
                src = even
        if face is None:
            raise FaceError('We could not see a face in the photo. Hold the phone at eye level, face a window '
                            'or a light (not with the light behind you), and try again.')
        if face[2] < 40 or face[3] < 40:
            raise FaceError('Your face is too small in the photo. Hold the phone closer and try again.')
        out = [recogniser.feature(recogniser.alignCrop(src, face))]
        other = even if src is img else img
        out.append(recogniser.feature(recogniser.alignCrop(other, face)))
    return [np.asarray(f, dtype=np.float32).reshape(-1) for f in out]


def embedding(image_bytes):
    """The face description (128 numbers, float32) of the largest face in the photo."""
    return embeddings(image_bytes)[0]


def best_match(vectors, references):
    """The highest similarity between any description of the new photo and any saved one of the person."""
    return max((similarity(v, r) for v in vectors for r in references), default=0.0)


def similarity(a, b):
    """Cosine similarity of two face descriptions: about 1 for the same person, about 0 for different people."""
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def to_bytes(vector):
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_bytes(raw):
    return np.frombuffer(bytes(raw), dtype=np.float32)
