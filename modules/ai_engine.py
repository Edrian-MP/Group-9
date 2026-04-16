import os
import numpy as np
import logging
import pickle
from collections import Counter
import config

try:
    import cv2
    _CV2_IMPORT_ERROR = None
except ImportError as cv2_error:
    cv2 = None
    _CV2_IMPORT_ERROR = cv2_error

try:
    from sklearn.neighbors import KNeighborsClassifier
    _SKLEARN_IMPORT_ERROR = None
except ImportError as sklearn_error:
    KNeighborsClassifier = None
    _SKLEARN_IMPORT_ERROR = sklearn_error

try:
    from tensorflow.keras.applications import MobileNetV2
    from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
    _TF_IMPORT_ERROR = None
except (ImportError, OSError) as tf_error:
    MobileNetV2 = None
    preprocess_input = None
    _TF_IMPORT_ERROR = tf_error

logger = logging.getLogger(__name__)

class AIEngine:
    def __init__(self):
        self.profiles_path = getattr(
            config,
            "PROFILES_PATH",
            os.path.join(config.BASE_DIR, "recognition_profiles.pkl")
        )

        self.feature_extractor = None
        self.classifier = (
            KNeighborsClassifier(n_neighbors=3, weights='distance')
            if KNeighborsClassifier is not None
            else None
        )
        self.database = {'features': [], 'labels': []}
        self.runtime_status = {
            "opencv_error": str(_CV2_IMPORT_ERROR) if _CV2_IMPORT_ERROR else None,
            "feature_extractor_ready": False,
            "feature_extractor_source": None,
            "model_error": None,
            "tensorflow_error": str(_TF_IMPORT_ERROR) if _TF_IMPORT_ERROR else None,
            "sklearn_error": str(_SKLEARN_IMPORT_ERROR) if _SKLEARN_IMPORT_ERROR else None,
            "profiles_path": self.profiles_path,
            "profiles_loaded": 0,
            "profiles_path_exists": os.path.exists(self.profiles_path),
            "profiles_error": None,
            "knn_trained": False,
            "online_weights_allowed": bool(getattr(config, "AI_ALLOW_ONLINE_WEIGHTS", True)),
        }

        if _SKLEARN_IMPORT_ERROR is not None:
            logger.error(
                "scikit-learn is unavailable; AI classification cannot run: %s",
                _SKLEARN_IMPORT_ERROR
            )
        if _CV2_IMPORT_ERROR is not None:
            logger.error(
                "OpenCV (cv2) is unavailable; AI feature extraction cannot run: %s",
                _CV2_IMPORT_ERROR
            )

        self.load_model()
        self.load_profiles()
        self._log_startup_summary()

    def _log_startup_summary(self):
        status = self.get_runtime_status()
        if status.get("feature_extractor_ready"):
            logger.info(
                "AI engine ready (extractor=%s, profiles=%d, knn_trained=%s)",
                status.get("feature_extractor_source"),
                status.get("profiles_loaded", 0),
                status.get("knn_trained", False),
            )
        else:
            logger.error(
                "AI engine unavailable: %s",
                status.get("model_error") or "unknown model initialization error",
            )

        if status.get("profiles_loaded", 0) == 0:
            logger.warning(
                "No recognition profiles loaded. Train products in Admin > Training."
            )

    def is_ready(self):
        return cv2 is not None and self.feature_extractor is not None and self.classifier is not None

    def get_runtime_status(self):
        status = dict(self.runtime_status)
        status["profiles_path"] = self.profiles_path
        status["profiles_path_exists"] = os.path.exists(self.profiles_path)
        status["profiles_loaded"] = len(self.database.get("labels", []))
        status["knn_trained"] = bool(self.classifier is not None and hasattr(self.classifier, "classes_"))
        return status

    def _model_unavailable_message(self):
        if cv2 is None:
            return "OpenCV is unavailable. Install opencv-python to enable image feature extraction."
        if self.classifier is None:
            return "scikit-learn is unavailable. Install scikit-learn to enable product classification."
        if self.feature_extractor is None:
            return self.runtime_status.get("model_error") or (
                "Feature extractor is unavailable. Configure MobileNetV2 weights or enable online weight download."
            )
        return ""

    def load_model(self):
        self.feature_extractor = None
        self.runtime_status["feature_extractor_ready"] = False
        self.runtime_status["feature_extractor_source"] = None
        self.runtime_status["model_error"] = None

        if MobileNetV2 is None or preprocess_input is None:
            model_error = (
                "TensorFlow/Keras import failed. Install TensorFlow 2.x and restart."
                f" Details: {_TF_IMPORT_ERROR}"
            )
            self.runtime_status["model_error"] = model_error
            logger.error(model_error)
            return

        configured_weights_path = str(getattr(config, "MOBILENET_WEIGHTS_PATH", "") or "").strip()
        allow_online_weights = bool(getattr(config, "AI_ALLOW_ONLINE_WEIGHTS", True))
        self.runtime_status["online_weights_allowed"] = allow_online_weights

        weights_arg = None
        source = None
        if configured_weights_path:
            expanded_path = os.path.expanduser(configured_weights_path)
            if not os.path.isabs(expanded_path):
                expanded_path = os.path.join(config.BASE_DIR, expanded_path)

            if os.path.exists(expanded_path):
                weights_arg = expanded_path
                source = "local-file"
            elif not allow_online_weights:
                model_error = (
                    "Configured MobileNetV2 weights file not found and online fallback is disabled: "
                    f"{expanded_path}"
                )
                self.runtime_status["model_error"] = model_error
                logger.error(model_error)
                return
            else:
                logger.warning(
                    "Configured MobileNetV2 weights file not found: %s. Falling back to online ImageNet weights.",
                    expanded_path,
                )

        if weights_arg is None:
            if allow_online_weights:
                weights_arg = "imagenet"
                source = "imagenet-online"
            else:
                model_error = (
                    "No local MobileNetV2 weights found and AI_ALLOW_ONLINE_WEIGHTS is disabled."
                )
                self.runtime_status["model_error"] = model_error
                logger.error(model_error)
                return

        try:
            self.feature_extractor = MobileNetV2(
                weights=weights_arg,
                include_top=False,
                pooling='avg',
                input_shape=(224, 224, 3)
            )
        except (OSError, RuntimeError, ValueError) as model_load_error:
            model_error = f"Failed to initialize MobileNetV2 ({source}): {model_load_error}"
            self.runtime_status["model_error"] = model_error
            logger.error(model_error)
            return

        self.runtime_status["feature_extractor_ready"] = True
        self.runtime_status["feature_extractor_source"] = source
        self.runtime_status["model_error"] = None
        logger.info("Successfully loaded Keras MobileNetV2 feature extractor from %s.", source)

    def load_profiles(self):
        self.runtime_status["profiles_error"] = None
        self.runtime_status["profiles_path_exists"] = os.path.exists(self.profiles_path)

        if not os.path.exists(self.profiles_path):
            logger.warning(
                "Recognition profile database not found at %s. Capture product profiles to enable AI recognition.",
                self.profiles_path,
            )
            self.runtime_status["profiles_loaded"] = 0
            return

        try:
            with open(self.profiles_path, 'rb') as profile_file:
                loaded_database = pickle.load(profile_file)
        except (OSError, pickle.UnpicklingError) as read_error:
            self.runtime_status["profiles_error"] = str(read_error)
            logger.error("Failed to read profiles from %s: %s", self.profiles_path, read_error)
            return

        if not isinstance(loaded_database, dict):
            self.runtime_status["profiles_error"] = "Profile file must contain a dictionary."
            logger.error("Invalid profile database format in %s", self.profiles_path)
            return

        features = loaded_database.get("features")
        labels = loaded_database.get("labels")
        if not isinstance(features, list) or not isinstance(labels, list):
            self.runtime_status["profiles_error"] = "Profile database must contain list fields: features and labels."
            logger.error("Invalid profile database content in %s", self.profiles_path)
            return

        if len(features) != len(labels):
            self.runtime_status["profiles_error"] = "Profile database is corrupted: feature/label counts do not match."
            logger.error("Corrupted profile database in %s", self.profiles_path)
            return

        self.database = {'features': features, 'labels': labels}
        self.runtime_status["profiles_loaded"] = len(labels)

        if self.database['labels']:
            try:
                self._train_knn()
            except (RuntimeError, ValueError) as train_error:
                self.runtime_status["profiles_error"] = str(train_error)
                logger.error("Failed to train KNN from loaded profiles: %s", train_error)

    def _train_knn(self):
        if self.classifier is None:
            self.runtime_status["knn_trained"] = False
            raise RuntimeError("scikit-learn classifier is unavailable.")

        label_count = len(self.database.get('labels', []))
        feature_count = len(self.database.get('features', []))
        if label_count != feature_count:
            self.runtime_status["knn_trained"] = False
            raise ValueError("Profile database is corrupted: feature/label counts do not match.")

        if label_count == 0:
            self.runtime_status["knn_trained"] = False
            return

        n_neighbors = min(3, label_count)
        self.classifier.n_neighbors = n_neighbors
        self.classifier.fit(self.database['features'], self.database['labels'])
        self.runtime_status["knn_trained"] = True

    def _persist_profiles(self):
        parent_dir = os.path.dirname(self.profiles_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        with open(self.profiles_path, 'wb') as profile_file:
            pickle.dump(self.database, profile_file)

        self.runtime_status["profiles_path_exists"] = os.path.exists(self.profiles_path)
        self.runtime_status["profiles_loaded"] = len(self.database.get("labels", []))
        self._train_knn()

    def _extract_features(self, frame):
        if self.feature_extractor is None or preprocess_input is None:
            return None
        if cv2 is None:
            return None
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        resized = cv2.resize(rgb_frame, (224, 224))
        
        input_data = np.expand_dims(resized, axis=0)
        
        processed_image = preprocess_input(input_data)
        
        features = self.feature_extractor.predict(processed_image, verbose=0)
        
        return features.flatten()

    def _predict_from_feature_vector(self, feature_vector, class_index_map=None):
        if feature_vector is None or not hasattr(self.classifier, 'classes_'):
            return None, 0.0

        prediction = self.classifier.predict([feature_vector])[0]
        probs = self.classifier.predict_proba([feature_vector])[0]
        if class_index_map is None:
            class_index_map = {label: idx for idx, label in enumerate(self.classifier.classes_)}
        class_index = class_index_map.get(prediction)
        confidence = float(probs[class_index]) if class_index is not None else 0.0
        return prediction, confidence

    def _classify_frame(self, frame, class_index_map=None):
        if frame is None:
            return None, 0.0
        feature_vector = self._extract_features(frame)
        return self._predict_from_feature_vector(feature_vector, class_index_map)

    def _classify_crop(self, frame, bbox, class_index_map=None):
        if frame is None or bbox is None:
            return None, 0.0

        frame_h, frame_w = frame.shape[:2]
        x, y, w, h = [int(v) for v in bbox]
        x = max(0, min(x, frame_w - 1))
        y = max(0, min(y, frame_h - 1))
        w = max(1, min(w, frame_w - x))
        h = max(1, min(h, frame_h - y))
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            return None, 0.0

        feature_vector = self._extract_features(crop)
        return self._predict_from_feature_vector(feature_vector, class_index_map)

    @staticmethod
    def _bbox_iou(box_a, box_b):
        ax, ay, aw, ah = box_a
        bx, by, bw, bh = box_b
        a_right, a_bottom = ax + aw, ay + ah
        b_right, b_bottom = bx + bw, by + bh

        inter_left = max(ax, bx)
        inter_top = max(ay, by)
        inter_right = min(a_right, b_right)
        inter_bottom = min(a_bottom, b_bottom)

        inter_w = max(0, inter_right - inter_left)
        inter_h = max(0, inter_bottom - inter_top)
        inter_area = inter_w * inter_h
        if inter_area <= 0:
            return 0.0

        area_a = max(1, aw * ah)
        area_b = max(1, bw * bh)
        return inter_area / float(area_a + area_b - inter_area)

    def _detect_object_candidates(self, frame):
        if cv2 is None:
            return []
        if frame is None or frame.size == 0:
            return []

        height, width = frame.shape[:2]
        frame_area = float(height * width)
        if frame_area <= 0:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred_gray = cv2.GaussianBlur(gray, (5, 5), 0)

        border_pixels = np.concatenate([
            blurred_gray[:8, :].ravel(),
            blurred_gray[-8:, :].ravel(),
            blurred_gray[:, :8].ravel(),
            blurred_gray[:, -8:].ravel()
        ])
        bg_intensity = int(np.median(border_pixels)) if border_pixels.size else int(np.median(blurred_gray))
        bg_reference = np.full_like(blurred_gray, bg_intensity)
        diff_from_bg = cv2.absdiff(blurred_gray, bg_reference)
        _, diff_mask = cv2.threshold(diff_from_bg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        sat_channel = cv2.GaussianBlur(hsv[:, :, 1], (5, 5), 0)
        _, sat_mask = cv2.threshold(sat_channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        mask = cv2.bitwise_or(diff_mask, sat_mask)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_area = max(250.0, frame_area * 0.008)
        max_area = frame_area * 0.90
        candidates = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < min_area or area > max_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w < 18 or h < 18:
                continue

            bbox_area = float(w * h)
            fill_ratio = area / bbox_area if bbox_area else 0.0
            aspect_ratio = float(w) / float(h)
            if fill_ratio < 0.20 or aspect_ratio < 0.30 or aspect_ratio > 3.5:
                continue

            if x <= 1 and y <= 1 and (x + w) >= (width - 1) and (y + h) >= (height - 1):
                continue

            pad = int(max(w, h) * 0.08)
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(width, x + w + pad)
            y2 = min(height, y + h + pad)
            candidates.append({'bbox': (x1, y1, x2 - x1, y2 - y1), 'area': area})

        candidates.sort(key=lambda item: item['area'], reverse=True)
        filtered_bboxes = []
        for candidate in candidates:
            bbox = candidate['bbox']
            if any(self._bbox_iou(bbox, selected) >= 0.45 for selected in filtered_bboxes):
                continue
            filtered_bboxes.append(bbox)
            if len(filtered_bboxes) >= 3:
                break

        filtered_bboxes.sort(key=lambda b: (b[1], b[0]))
        return filtered_bboxes

    def predict_object_detections(self, frames, frame_indices=None):
        result = {
            'detections': [],
            'per_frame_detections': [],
            'active_frame_count': 0
        }

        if (
            not self.database['labels']
            or self.feature_extractor is None
            or self.classifier is None
            or frames is None
        ):
            return result

        if not hasattr(self.classifier, 'classes_'):
            try:
                self._train_knn()
            except (RuntimeError, ValueError) as knn_error:
                logger.warning("KNN unavailable for object detection: %s", knn_error)
                return result
            if not hasattr(self.classifier, 'classes_'):
                return result

        if not isinstance(frames, (list, tuple)):
            frames = [frames]

        if len(frames) == 0:
            return result

        allowed_indices = None
        if frame_indices is not None:
            allowed_indices = set()
            for item in frame_indices:
                try:
                    idx = int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= idx < len(frames):
                    allowed_indices.add(idx)
            if not allowed_indices:
                return result

        class_index_map = {label: idx for idx, label in enumerate(self.classifier.classes_)}

        for frame_index, frame in enumerate(frames):
            frame_result = {
                'frame_index': frame_index,
                'camera_index': frame_index,
                'detections': [],
                'active': False
            }

            if allowed_indices is not None and frame_index not in allowed_indices:
                result['per_frame_detections'].append(frame_result)
                continue

            if frame is not None:
                try:
                    for bbox_index, bbox in enumerate(self._detect_object_candidates(frame)):
                        if bbox_index >= 2:
                            break
                        label, confidence = self._classify_crop(frame, bbox, class_index_map)
                        if not label:
                            continue
                        frame_result['detections'].append({
                            'bbox': [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                            'label': label,
                            'confidence': float(confidence),
                            'frame_index': frame_index,
                            'camera_index': frame_index
                        })
                except Exception as frame_error:
                    logger.warning("Frame %d object detection error: %s", frame_index, frame_error)

            if frame_result['detections']:
                frame_result['detections'].sort(key=lambda det: det['confidence'], reverse=True)
                frame_result['active'] = True
                result['active_frame_count'] += 1
                result['detections'].extend(frame_result['detections'])

            result['per_frame_detections'].append(frame_result)

        return result

    def predict_product_detailed(self, frames):
        empty_result = {
            'fused_label': None,
            'fused_confidence': 0.0,
            'per_frame_predictions': [],
            'vote_counts': {},
            'active_frame_count': 0,
            'object_detections': [],
            'per_frame_detections': [],
            'fallback_frame_indices': [],
            'pipeline_mode': 'none'
        }

        if (
            not self.database['labels']
            or self.feature_extractor is None
            or self.classifier is None
            or frames is None
        ):
            return empty_result

        if not hasattr(self.classifier, 'classes_'):
            try:
                self._train_knn()
            except (RuntimeError, ValueError) as knn_error:
                logger.warning("KNN unavailable for product prediction: %s", knn_error)
                return empty_result
            if not hasattr(self.classifier, 'classes_'):
                return empty_result

        if not isinstance(frames, (list, tuple)):
            frames = [frames]

        if len(frames) == 0:
            return empty_result

        try:
            class_index_map = {label: idx for idx, label in enumerate(self.classifier.classes_)}
            fast_pass_predictions = []
            fast_pass_confidences = []

            for frame_index, frame in enumerate(frames):
                if frame is None:
                    empty_result['per_frame_predictions'].append({
                        'frame_index': frame_index,
                        'label': None,
                        'confidence': 0.0,
                        'active': False
                    })
                    continue

                try:
                    prediction, prediction_confidence = self._classify_frame(frame, class_index_map)

                    if not prediction:
                        empty_result['per_frame_predictions'].append({
                            'frame_index': frame_index,
                            'label': None,
                            'confidence': 0.0,
                            'active': False
                        })
                        continue

                    empty_result['per_frame_predictions'].append({
                        'frame_index': frame_index,
                        'label': prediction,
                        'confidence': prediction_confidence,
                        'active': True
                    })

                    fast_pass_predictions.append(prediction)
                    fast_pass_confidences.append((prediction, prediction_confidence))
                except Exception as frame_error:
                    logger.warning("Frame %d prediction error: %s", frame_index, frame_error)
                    empty_result['per_frame_predictions'].append({
                        'frame_index': frame_index,
                        'label': None,
                        'confidence': 0.0,
                        'active': False
                    })

            empty_result['active_frame_count'] = len(fast_pass_predictions)
            if not fast_pass_predictions:
                return empty_result

            vote_counter = Counter(fast_pass_predictions)
            most_common_label, _ = vote_counter.most_common(1)[0]
            winning_confidences = [
                confidence
                for prediction, confidence in fast_pass_confidences
                if prediction == most_common_label
            ]
            avg_conf = float(np.mean(winning_confidences)) if winning_confidences else 0.0

            quick_confidence_ok = avg_conf >= 0.80
            if quick_agreement_ok and quick_confidence_ok:
                empty_result['fused_label'] = most_common_label
                empty_result['fused_confidence'] = avg_conf
                empty_result['vote_counts'] = dict(vote_counter)
                empty_result['pipeline_mode'] = 'fast_frame'
                return empty_result

            medium_confidence_ok = avg_conf >= 0.72
            if quick_agreement_ok and medium_confidence_ok:
                empty_result['fused_label'] = most_common_label
                empty_result['fused_confidence'] = avg_conf
                empty_result['vote_counts'] = dict(vote_counter)
                empty_result['pipeline_mode'] = 'frame_only'
                return empty_result

            fallback_candidates = []
            for item in empty_result['per_frame_predictions']:
                if not isinstance(item, dict) or not bool(item.get('active')):
                    continue
                frame_index = int(item.get('frame_index', -1))
                if frame_index < 0:
                    continue
                frame_label = str(item.get('label') or "")
                frame_conf = float(item.get('confidence') or 0.0)
                disagreement_rank = 0 if frame_label != most_common_label else 1
                fallback_candidates.append((disagreement_rank, frame_conf, frame_index))

            fallback_candidates.sort(key=lambda row: (row[0], row[1]))
            fallback_frame_indices = [frame_index for _, _, frame_index in fallback_candidates[:1]]
            if not fallback_frame_indices and empty_result['per_frame_predictions']:
                active_indices = [
                    int(item.get('frame_index', 0))
                    for item in empty_result['per_frame_predictions']
                    if isinstance(item, dict) and bool(item.get('active'))
                ]
                if active_indices:
                    fallback_frame_indices = [active_indices[0]]

            detection_result = self.predict_object_detections(frames, frame_indices=fallback_frame_indices)
            empty_result['object_detections'] = detection_result['detections']
            empty_result['per_frame_detections'] = detection_result['per_frame_detections']
            empty_result['fallback_frame_indices'] = fallback_frame_indices
            empty_result['pipeline_mode'] = 'fallback_detection'

            if detection_result['detections']:
                refined_predictions = []
                refined_confidences = []
                refined_per_frame = []
                frame_detection_lookup = {
                    item['frame_index']: item.get('detections', [])
                    for item in detection_result['per_frame_detections']
                }

                for frame_index, prior in enumerate(empty_result['per_frame_predictions']):
                    if not bool(prior.get('active')):
                        refined_per_frame.append(prior)
                        continue

                    frame_detections = frame_detection_lookup.get(frame_index, [])
                    if frame_detections:
                        best_detection = max(frame_detections, key=lambda det: det.get('confidence', 0.0))
                        prediction = best_detection.get('label')
                        prediction_confidence = float(best_detection.get('confidence') or 0.0)
                    else:
                        prediction = prior.get('label')
                        prediction_confidence = float(prior.get('confidence') or 0.0)

                    if not prediction:
                        refined_per_frame.append({
                            'frame_index': frame_index,
                            'label': None,
                            'confidence': 0.0,
                            'active': False
                        })
                        continue

                    refined_per_frame.append({
                        'frame_index': frame_index,
                        'label': prediction,
                        'confidence': prediction_confidence,
                        'active': True
                    })
                    refined_predictions.append(prediction)
                    refined_confidences.append((prediction, prediction_confidence))

                if refined_predictions:
                    empty_result['per_frame_predictions'] = refined_per_frame
                    empty_result['active_frame_count'] = len(refined_predictions)
                    vote_counter = Counter(refined_predictions)
                    most_common_label, _ = vote_counter.most_common(1)[0]
                    winning_confidences = [
                        confidence
                        for prediction, confidence in refined_confidences
                        if prediction == most_common_label
                    ]
                    avg_conf = float(np.mean(winning_confidences)) if winning_confidences else 0.0

            empty_result['fused_label'] = most_common_label
            empty_result['fused_confidence'] = avg_conf
            empty_result['vote_counts'] = dict(vote_counter)
            if not detection_result['detections']:
                empty_result['pipeline_mode'] = 'frame_only'
            return empty_result
        except Exception as e:
            logger.warning("Prediction error: %s", e)
            return empty_result

    def predict_product(self, frames):
        detailed_result = self.predict_product_detailed(frames)
        return detailed_result['fused_label'], detailed_result['fused_confidence']

    def capture_training_data(self, label, frames):
        label = str(label or "").strip()
        if not label:
            raise ValueError("Product label is required.")
        if frames is None:
            raise ValueError("No frame available from camera.")

        if not isinstance(frames, (list, tuple)):
            frames = [frames]

        valid_frames = [frame for frame in frames if frame is not None]
        if not valid_frames:
            raise ValueError("No valid frames available from camera.")

        if not self.is_ready():
            return f"Error: {self._model_unavailable_message()}"

        saved_count = 0
        for frame in valid_frames:
            feature_vector = self._extract_features(frame)
            if feature_vector is None:
                continue

            self.database['features'].append(feature_vector)
            self.database['labels'].append(label)
            saved_count += 1

        if saved_count == 0:
            if not self.is_ready():
                return f"Error: {self._model_unavailable_message()}"
            return "No valid frames could be processed for training."

        self._persist_profiles()

        logger.info("Generated and saved %d recognition profiles for: %s", saved_count, label)
        return f"{saved_count} profiles saved for {label} from multi-camera capture"

    def capture_training_data_from_paths(self, label, image_paths):
        if not label or not str(label).strip():
            raise ValueError("Product label is required.")
        if image_paths is None:
            raise ValueError("No image paths provided.")
        if not isinstance(image_paths, (list, tuple)):
            image_paths = [image_paths]

        normalized_paths = [path for path in image_paths if isinstance(path, str) and path.strip()]
        if not normalized_paths:
            raise ValueError("No valid image paths provided.")

        if not self.is_ready():
            return {
                "saved_count": 0,
                "skipped_count": len(normalized_paths),
                "message": f"Error: {self._model_unavailable_message()}"
            }

        saved_count = 0
        skipped_count = 0
        for image_path in normalized_paths:
            frame = cv2.imread(image_path)
            if frame is None:
                skipped_count += 1
                continue

            feature_vector = self._extract_features(frame)
            if feature_vector is None:
                skipped_count += 1
                continue

            self.database['features'].append(feature_vector)
            self.database['labels'].append(label)
            saved_count += 1

        if saved_count == 0:
            if not self.is_ready():
                return {
                    "saved_count": 0,
                    "skipped_count": skipped_count,
                    "message": f"Error: {self._model_unavailable_message()}"
                }
            return {
                "saved_count": 0,
                "skipped_count": skipped_count,
                "message": "No valid images were imported from the selected folder."
            }

        self._persist_profiles()

        logger.info("Imported and saved %d recognition profiles for: %s (skipped %d)",
                    saved_count, label, skipped_count)
        message = f"{saved_count} profiles saved for {label} from folder upload"
        if skipped_count > 0:
            message = f"{message} ({skipped_count} skipped)"
        return {
            "saved_count": saved_count,
            "skipped_count": skipped_count,
            "message": message
        }

