import os

class GateConfig:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'smart-souvenir-gate-secret-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('GATE_DATABASE_URL', 'sqlite:///gate.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Camera settings (0 = use device native resolution)
    CAMERA_INDEX = int(os.environ.get('CAMERA_INDEX', 0))
    CAMERA_WIDTH = int(os.environ.get('CAMERA_WIDTH', 0))
    CAMERA_HEIGHT = int(os.environ.get('CAMERA_HEIGHT', 0))
    
    # ML settings
    ML_MODEL_PATH = os.environ.get('ML_MODEL_PATH', os.path.join(os.path.dirname(__file__), 'models', 'best1.pt'))
    DETECTION_CONFIDENCE = float(os.environ.get('DETECTION_CONFIDENCE', '0.35'))
    
    # App settings
    MAX_VISITORS_LOG = 1000
    GATE_STATUS = 'open'
