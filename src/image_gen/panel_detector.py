"""Panel element detection module using OpenCV.

This module detects empty speech bubbles and narration boxes in comic panel
images using contour detection and filtering techniques.
"""

from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np


@dataclass
class DetectedRegion:
    """Represents a detected panel region (speech bubble, thought bubble, or narration box)."""

    x: int  # Top-left x coordinate
    y: int  # Top-left y coordinate
    width: int
    height: int
    contour: np.ndarray  # Original contour points
    mask: Optional[np.ndarray] = None  # Binary mask of the region shape
    center_x: int = 0
    center_y: int = 0
    area: int = 0

    def __post_init__(self):
        self.center_x = self.x + self.width // 2
        self.center_y = self.y + self.height // 2
        self.area = self.width * self.height


# Keep old name as alias for backwards compatibility
DetectedBubble = DetectedRegion


class PanelDetector:
    """Detects empty speech bubbles and narration boxes in comic images using OpenCV."""
    def __init__(
        self,
        min_area: int = 70000,
        max_area: int = 250000,
        white_threshold: int = 180,
        kernel_size: int = 3,
        min_circularity: float = 0.52,
        min_rectangularity: float = 0.7,
    ):
        """Initialize the panel detector.

        Args:
            min_area: Minimum contour area to consider.
            max_area: Maximum contour area to consider.
            white_threshold: Threshold for white detection (0-255).
            min_circularity: Minimum circularity ratio for bubble shapes.
            kernel_size: Morphological kernel size for cleanup.
            min_rectangularity: Minimum rectangularity ratio for narration boxes.
        """
        self.min_area = min_area
        self.max_area = max_area
        self.white_threshold = white_threshold
        self.kernel_size = kernel_size
        self.min_circularity = min_circularity
        self.min_rectangularity = min_rectangularity

    def _preprocess_image(self, image_data: bytes):
        """Decode image bytes and extract contours from white regions.

        Args:
            image_data: Raw image bytes (e.g. PNG).

        Returns:
            Tuple of (contours, height, width) or None if decoding fails.
        """
        img = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None

        height, width = img.shape[:2]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, self.white_threshold, 255, cv2.THRESH_BINARY)
        inverse = cv2.bitwise_not(binary)

        kernel = np.ones((self.kernel_size, self.kernel_size), np.uint8)
        cleaned = cv2.morphologyEx(inverse, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(cleaned, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        return contours, height, width

    def _is_near_edge(self, x: int, y: int, w: int, h: int, img_width: int, img_height: int, margin: int = 10) -> bool:
        """Check if a region is a background-like edge region that should be skipped.

        Returns True if the region touches an image edge and spans more than
        50% of that edge, indicating it is likely background rather than a
        bubble or box.
        """
        if x < margin or y < margin or x + w > img_width - margin or y + h > img_height - margin:
            edge_ratio = 0
            if x < margin:
                edge_ratio = max(edge_ratio, h / img_height)
            if y < margin:
                edge_ratio = max(edge_ratio, w / img_width)
            if x + w > img_width - margin:
                edge_ratio = max(edge_ratio, h / img_height)
            if y + h > img_height - margin:
                edge_ratio = max(edge_ratio, w / img_width)

            if edge_ratio > 0.5:
                return True

        return False

    def _build_region(self, contour: np.ndarray, x: int, y: int, w: int, h: int, img_height: int, img_width: int, area: int) -> DetectedRegion:
        """Create a DetectedRegion with a binary mask from a contour."""
        mask = np.zeros((img_height, img_width), dtype=np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, -1)

        return DetectedRegion(
            x=x, y=y, width=w, height=h,
            contour=contour, mask=mask, area=area,
        )

    def detect_bubbles(self, image_data: bytes) -> List[DetectedRegion]:
        """Detect speech bubbles in an image.

        Args:
            image_data: Raw image bytes (e.g. PNG).

        Returns:
            List of DetectedRegion objects, sorted by position (top-to-bottom, left-to-right).
        """
        result = self._preprocess_image(image_data)
        if result is None:
            return []

        contours, height, width = result
        bubbles = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area or area > self.max_area:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < self.min_circularity:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if self._is_near_edge(x, y, w, h, width, height):
                continue

            bubbles.append(self._build_region(contour, x, y, w, h, height, width, int(area)))

        if bubbles:
            bubbles = self._sort_reading_order(bubbles, height)

        return bubbles

    def detect_narration_boxes(self, image_data: bytes) -> List[DetectedRegion]:
        """Detect rectangular narration boxes using white-threshold approach.

        Uses the same preprocessing as speech bubbles,
        but filters for rectangular shapes instead of circular ones.

        Args:
            image_data: Raw image bytes (e.g. PNG).

        Returns:
            List of DetectedRegion objects for detected narration boxes.
        """
        result = self._preprocess_image(image_data)
        if result is None:
            return []

        contours, height, width = result
        boxes = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area or area > self.max_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            rect_area = w * h
            rectangularity = area / rect_area if rect_area > 0 else 0
            if rectangularity < self.min_rectangularity:
                continue

            if self._is_near_edge(x, y, w, h, width, height):
                continue

            boxes.append(self._build_region(contour, x, y, w, h, height, width, int(area)))

        if boxes:
            boxes = self._sort_reading_order(boxes, height)

        return boxes

    def _sort_reading_order(
        self, regions: List[DetectedRegion], image_height: int
    ) -> List[DetectedRegion]:
        """Sort regions in reading order (top-to-bottom, left-to-right).

        Args:
            regions: List of detected regions.
            image_height: Height of the image for row grouping.

        Returns:
            Sorted list of regions.
        """
        # Group regions into rows based on their vertical center
        row_threshold = image_height * 0.15  # Regions within 15% of image height are same row

        # Sort by y-center first
        regions_sorted = sorted(regions, key=lambda b: b.center_y)

        rows = []
        current_row = [regions_sorted[0]]
        current_row_y = regions_sorted[0].center_y

        for region in regions_sorted[1:]:
            if abs(region.center_y - current_row_y) < row_threshold:
                current_row.append(region)
            else:
                rows.append(current_row)
                current_row = [region]
                current_row_y = region.center_y
        rows.append(current_row)

        # Sort each row by x-center (left to right)
        result = []
        for row in rows:
            row_sorted = sorted(row, key=lambda b: b.center_x)
            result.extend(row_sorted)

        return result


# Keep old name as alias for backwards compatibility
BubbleDetector = PanelDetector
