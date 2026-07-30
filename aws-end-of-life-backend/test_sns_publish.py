import sys
import logging
logging.basicConfig(level=logging.INFO)
sys.path.append("/home/vikas-singh/Documents/EOL-Project/EndOfLifeAWS-Project/aws-end-of-life-backend")
from sns_service import publish_alert
try:
    # Need a real topic_arn, let's create one or use a dummy one
    publish_alert("arn:aws:sns:us-east-1:164761934067:eolm-ws-ws_6a042c70a02dd146", "Test Subject", "Test Body")
except Exception as e:
    import traceback
    traceback.print_exc()
