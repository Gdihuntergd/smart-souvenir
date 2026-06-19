"""
Database models for Gate component visitor logging.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class VisitorLog(db.Model):
    """Log of visitors detected at the gate."""
    __tablename__ = 'visitor_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    detected_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    visitor_count = db.Column(db.Integer, default=0)
    confidence_avg = db.Column(db.Float, default=0.0)
    gate_status = db.Column(db.String(10), default='open')
    detection_data = db.Column(db.Text, nullable=True)
    image_path = db.Column(db.String(255), nullable=True)
    
    def __repr__(self):
        return f'<VisitorLog {self.id} - {self.detected_at} - {self.visitor_count} visitors>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'detected_at': self.detected_at.strftime('%Y-%m-%d %H:%M:%S'),
            'visitor_count': self.visitor_count,
            'confidence_avg': round(self.confidence_avg, 2),
            'gate_status': self.gate_status,
            'detection_data': self.detection_data,
            'image_path': self.image_path
        }


class GateStats(db.Model):
    """Aggregate statistics for the gate."""
    __tablename__ = 'gate_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=datetime.now().date, nullable=False)
    total_visitors = db.Column(db.Integer, default=0)
    total_detections = db.Column(db.Integer, default=0)
    avg_confidence = db.Column(db.Float, default=0.0)
    peak_hour = db.Column(db.Integer, nullable=True)
    
    def __repr__(self):
        return f'<GateStats {self.date} - {self.total_visitors} total>'
