import boto3
import sys

sns = boto3.client('sns', region_name='us-east-1')
try:
    sns.confirm_subscription(
        TopicArn="arn:aws:sns:us-east-1:123456789012:test",
        Token="token",
        AuthenticateOnUnsubscribe="true",
        InvalidArg="test"
    )
except Exception as e:
    print(f"Exception Type: {type(e).__name__}")
    print(f"Exception: {e}")
