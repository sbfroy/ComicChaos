"""Bubble detection module using OpenCV.

This module detects empty speech bubbles in comic panel images using
contour detection and filtering techniques.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass
class DetectedBubble:
    """Represents a detected speech/thought bubble region."""

    x: int  # Top-left x coordinate
    y: int  # Top-left y coordinate
    width: int
    height: int
    contour: np.ndarray  # Original contour points
    mask: Optional[np.ndarray] = None  # Binary mask of the bubble shape
    center_x: int = 0
    center_y: int = 0
    area: int = 0

    def __post_init__(self):
        self.center_x = self.x + self.width // 2
        self.center_y = self.y + self.height // 2
        self.area = self.width * self.height


class BubbleDetector:
    """Detects empty speech bubbles in comic images using OpenCV."""
    def __init__(
        self,
        min_bubble_area: int = 70000,
        max_bubble_area: int = 250000,
        white_threshold: int = 180,
        min_circularity: float = 0.52,
        kernel_size: int = 3,
    ):
        """Initialize the bubble detector.

        Args:
            min_bubble_area: Minimum contour area to consider as a bubble.
            max_bubble_area: Maximum contour area to consider as a bubble.
            white_threshold: Threshold for white detection (0-255).
            min_circularity: Minimum circularity ratio for bubble shapes.
        """
        self.min_bubble_area = min_bubble_area
        self.max_bubble_area = max_bubble_area
        self.white_threshold = white_threshold
        self.min_circularity = min_circularity
        self.kernel_size = kernel_size

    def detect_bubbles(self, image_path: str) -> List[DetectedBubble]:
        """Detect speech bubbles in an image.

        Args:
            image_path: Path to the image file.

        Returns:
            List of DetectedBubble objects, sorted by position (top-to-bottom, left-to-right).
        """
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            return []

        return self._detect_bubbles_from_array(img)

    def detect_bubbles_from_pil(self, pil_image: Image.Image) -> List[DetectedBubble]:
        """Detect speech bubbles from a PIL Image.

        Args:
            pil_image: PIL Image object.

        Returns:
            List of DetectedBubble objects.
        """
        # Convert PIL to OpenCV format (RGB to BGR)
        img_array = np.array(pil_image)
        if len(img_array.shape) == 3 and img_array.shape[2] == 3:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        elif len(img_array.shape) == 3 and img_array.shape[2] == 4:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)

        return self._detect_bubbles_from_array(img_array)

    def _detect_bubbles_from_array(self, img: np.ndarray) -> List[DetectedBubble]:
        """Internal method to detect bubbles from a numpy array.

        Args:
            img: OpenCV image array (BGR format).

        Returns:
            List of DetectedBubble objects.
        """
        height, width = img.shape[:2]

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply threshold to find white regions (bubbles are typically white)
        _, binary = cv2.threshold(gray, self.white_threshold, 255, cv2.THRESH_BINARY)

        # Apply morphological operations to clean up the mask
        kernel = np.ones((self.kernel_size, self.kernel_size), np.uint8)

        inverse = cv2.bitwise_not(binary)

        # 
        after_close = cv2.morphologyEx(inverse, cv2.MORPH_CLOSE, kernel, iterations=2)
        
        # Find contours
        contours, _ = cv2.findContours(after_close, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        bubbles = []

        for contour in contours:
            # Calculate area
            area = cv2.contourArea(contour)

            # Filter by area
            if area < self.min_bubble_area or area > self.max_bubble_area:
                continue

            # Calculate circularity (4 * pi * area / perimeter^2)
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)

            # Filter by circularity (bubbles are generally rounded)
            if circularity < self.min_circularity:
                continue

            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(contour)

            # Filter out regions that are too close to edges (likely background)
            margin = 10
            if x < margin or y < margin or x + w > width - margin or y + h > height - margin:
                # Check if it's a large portion of the edge - if so, skip
                edge_ratio = 0
                if x < margin:
                    edge_ratio = max(edge_ratio, h / height)
                if y < margin:
                    edge_ratio = max(edge_ratio, w / width)
                if x + w > width - margin:
                    edge_ratio = max(edge_ratio, h / height)
                if y + h > height - margin:
                    edge_ratio = max(edge_ratio, w / width)

                # If more than 50% of an edge, it's probably background
                if edge_ratio > 0.5:
                    continue

            # Create a mask for this specific bubble
            mask = np.zeros((height, width), dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)

            bubble = DetectedBubble(
                x=x,
                y=y,
                width=w,
                height=h,
                contour=contour,
                mask=mask,
                area=int(area)
            )
            bubbles.append(bubble)

        # Sort by position: top-to-bottom, then left-to-right
        # Using a grid-based approach to group bubbles in rows
        if bubbles:
            bubbles = self._sort_bubbles_reading_order(bubbles, height)

        return bubbles

    def _sort_bubbles_reading_order(
        self, bubbles: List[DetectedBubble], image_height: int
    ) -> List[DetectedBubble]:
        """Sort bubbles in reading order (top-to-bottom, left-to-right).

        Args:
            bubbles: List of detected bubbles.
            image_height: Height of the image for row grouping.

        Returns:
            Sorted list of bubbles.
        """
        # Group bubbles into rows based on their vertical center
        row_threshold = image_height * 0.15  # Bubbles within 15% of image height are same row

        # Sort by y-center first
        bubbles_sorted = sorted(bubbles, key=lambda b: b.center_y)

        rows = []
        current_row = [bubbles_sorted[0]]
        current_row_y = bubbles_sorted[0].center_y

        for bubble in bubbles_sorted[1:]:
            if abs(bubble.center_y - current_row_y) < row_threshold:
                current_row.append(bubble)
            else:
                rows.append(current_row)
                current_row = [bubble]
                current_row_y = bubble.center_y
        rows.append(current_row)

        # Sort each row by x-center (left to right)
        result = []
        for row in rows:
            row_sorted = sorted(row, key=lambda b: b.center_x)
            result.extend(row_sorted)

        return result

    def create_debug_image(
        self, image_path: str, bubbles: List[DetectedBubble], output_path: str
    ) -> None:
        """Create a debug image showing detected bubbles.

        Args:
            image_path: Path to the original image.
            bubbles: List of detected bubbles.
            output_path: Path to save the debug image.
        """
        img = cv2.imread(image_path)
        if img is None:
            return

        for i, bubble in enumerate(bubbles):
            # Draw contour
            cv2.drawContours(img, [bubble.contour], -1, (0, 255, 0), 2)

            # Draw bounding rectangle
            cv2.rectangle(
                img,
                (bubble.x, bubble.y),
                (bubble.x + bubble.width, bubble.y + bubble.height),
                (255, 0, 0),
                2
            )

            # Draw bubble number
            cv2.putText(
                img,
                str(i + 1),
                (bubble.center_x - 10, bubble.center_y + 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2
            )

        cv2.imwrite(output_path, img)
