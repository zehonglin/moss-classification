from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtGui import QPixmap, QFont, QImageReader
from PySide6.QtCore import Qt, QSize
from datetime import datetime


class HistoryItemWidget(QWidget):
    """
    Custom widget for displaying a single history item in the QListWidget.
    
    Memory Optimization:
    - Uses QImageReader.setScaledSize() for efficient thumbnail loading
    - Loads scaled image directly instead of full image + resize
    """
    
    # Thumbnail size constant
    THUMBNAIL_SIZE = 60
    
    def __init__(self, image_path, timestamp_str, original_pred, confidence, corrected_label, confidence_threshold=0.6):
        super().__init__()
        
        # Main horizontal layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- Thumbnail (Left) ---
        thumbnail_label = QLabel()
        thumbnail_label.setFixedSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        
        # Optimized thumbnail loading using QImageReader
        # This loads the image at the target size directly, saving memory
        try:
            reader = QImageReader(image_path)
            if reader.canRead():
                # Get original size to calculate aspect ratio
                original_size = reader.size()
                if original_size.isValid():
                    # Calculate scaled size maintaining aspect ratio
                    scaled_size = original_size.scaled(
                        QSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE),
                        Qt.KeepAspectRatio
                    )
                    # Set the scaled size BEFORE reading - this is the key optimization
                    reader.setScaledSize(scaled_size)
                
                # Read the already-scaled image
                image = reader.read()
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
                    thumbnail_label.setPixmap(pixmap)
                else:
                    thumbnail_label.setText("无图")
                    thumbnail_label.setStyleSheet("color: #78909C; font-size: 8px;")
            else:
                thumbnail_label.setText("无图")
                thumbnail_label.setStyleSheet("color: #78909C; font-size: 8px;")
        except Exception:
            thumbnail_label.setText("错误")
            thumbnail_label.setStyleSheet("color: #FF5252; font-size: 8px;")
            
        main_layout.addWidget(thumbnail_label, 0, Qt.AlignVCenter)

        # --- Info (Right - Vertical Layout for Time, Prediction, Correction) ---
        info_vertical_layout = QVBoxLayout()
        info_vertical_layout.setContentsMargins(0, 0, 0, 0)
        info_vertical_layout.setSpacing(2)

        # Timestamp Label (Row 1 of Info)
        try:
            dt_object = datetime.fromisoformat(timestamp_str)
            formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            formatted_time = timestamp_str

        time_label = QLabel(formatted_time)
        font = time_label.font()
        font.setPointSize(10)
        time_label.setFont(font)
        time_label.setStyleSheet("color: #90A4AE;")
        
        # Prediction & Correction Row (Row 2 of Info)
        pred_corr_horizontal_layout = QHBoxLayout()
        pred_corr_horizontal_layout.setContentsMargins(0, 0, 0, 0)
        pred_corr_horizontal_layout.setSpacing(8)

        # Prediction Label with confidence (Left of Row 2)
        is_corrected = corrected_label and corrected_label != "None"
        needs_review = (not is_corrected) and isinstance(confidence, (int, float)) and confidence < confidence_threshold
        confidence_str = f" ({confidence:.1%})" if isinstance(confidence, (int, float)) else ""
        prefix = "⚠️ " if needs_review else ""
        prediction_label = QLabel(f"{prefix}{original_pred}{confidence_str}")
        font = prediction_label.font()
        font.setPointSize(14)
        font.setBold(True)
        prediction_label.setFont(font)
        prediction_label.setStyleSheet("color: #FFA726;" if needs_review else "color: #ECEFF1;")

        # Correction Label (Right of Row 2)
        correction_label = QLabel("")
        font = correction_label.font()
        font.setPointSize(12)
        correction_label.setFont(font)
        correction_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        if corrected_label and corrected_label != "None":
            correction_label.setText(f"纠错: {corrected_label}")
            correction_label.setStyleSheet("color: #80CBC4;")
            prediction_label.setStyleSheet("color: #78909C; text-decoration: line-through;")
        
        pred_corr_horizontal_layout.addWidget(prediction_label)
        pred_corr_horizontal_layout.addStretch()
        pred_corr_horizontal_layout.addWidget(correction_label)

        info_vertical_layout.addWidget(time_label)
        info_vertical_layout.addLayout(pred_corr_horizontal_layout)
        info_vertical_layout.addStretch()

        main_layout.addLayout(info_vertical_layout)
        self.setMinimumHeight(80)

