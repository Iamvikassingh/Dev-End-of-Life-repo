import boto3
import os

sns = boto3.client('sns', region_name='us-east-1')
topic_arn = sns.create_topic(Name='test-auth-unsubscribe')['TopicArn']
print(f"Topic: {topic_arn}")

sub_arn = sns.subscribe(TopicArn=topic_arn, Protocol='email', Endpoint='test@example.com')['SubscriptionArn']
print(f"Sub ARN: {sub_arn}")
