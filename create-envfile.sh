#!/bin/bash

STACK_NAME="bluearch-alerting-engine-cli-dev"

get_output_value() {
    aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo "export BUCKET_NAME=\"$(get_output_value 'BucketName')\"" >> .env
echo "export TOPIC_ARN=\"$(get_output_value 'TopicArn')\"" >> .env
echo "export ROLE_NAME=\"$(get_output_value 'RoleName')\"" >> .env
echo "export ROLE_EXTERNAL_ID=\"BlueArchAlertingEngineAPIExternalID\"" >> .env
echo "export ROLE_SESSION_NAME=\"BlueArchAlertsEngine\"" >> .env
echo "export CURRENT_REGION=\"$(get_output_value 'Region')\"" >> .env
echo "export CURRENT_ACCOUNT_ID=\"$(get_output_value 'AccountID')\"" >> .env
echo "export STATE_MACHINE_ARN=\"$(get_output_value 'StateMachineArn')\"" >> .env
echo "export STACKSET_ID=\"$(get_output_value 'StackSetID')\"" >> .env
echo "export BLUEARCH_DEBUG=1" >> .env
echo "export WORKSPACE=\"$(get_output_value 'Workspace')\"" >> .env
echo "export ACC_TABLE_NAME=\"$(get_output_value 'AccTableName')\"" >> .env
echo "export REC_TABLE_NAME=\"$(get_output_value 'RecTableName')\"" >> .env
echo "export SECRET_ARN=\"$(get_output_value 'SecretArn')\"" >> .env

echo "Environment variables exported to .env file."