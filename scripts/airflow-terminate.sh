#!/bin/bash
INSTANCE_ID=$(ec2-metadata -i | awk '{print $2}')
TERMINATE_MESSAGE="Terminating EC2 instance: $INSTANCE_ID"
TERMINATING=$(aws autoscaling describe-scaling-activities \
    --auto-scaling-group-name "$AWS_AUTO_SCALING_GROUP_NAME" \
    --max-items 100 \
    --region "$AWS_DEFAULT_REGION" | \
    jq --arg TERMINATE_MESSAGE "$TERMINATE_MESSAGE" \
    '.Activities[]
    | select(.Description
    | test($TERMINATE_MESSAGE)) != []')

if [ "$TERMINATING" = "true" ]; then
    sudo systemctl start airflow-heartbeat.timer
    systemctl stop airflow-workerset
    aws autoscaling complete-lifecycle-action \
    --instance-id "$(ec2-metadata -i | awk '{print $2}')" \
    --lifecycle-hook-name "$AWS_SHUTDOWN_LIFECYCLE_NAME" \
    --auto-scaling-group-name "$AWS_AUTO_SCALING_GROUP_NAME" \
    --lifecycle-action-result CONTINUE \
    --region "$AWS_DEFAULT_REGION"
fi
