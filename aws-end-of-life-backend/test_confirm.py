import boto3

sns = boto3.client('sns', region_name='us-east-1')

try:
    sns.confirm_subscription(
        TopicArn="arn:aws:sns:us-east-1:123456789012:test-auth-unsubscribe",
        Token="fake_token",
        AuthenticateOnUnsubscribe="true"
    )
except Exception as e:
    print(f"Error: {e}")
