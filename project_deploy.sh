#!/bin/bash

# (c) Dativa 2019, all rights reserved

STAGE=${1:-"TEST"}
PROFILE=${2:-""}
REGION=${3:-"us-east-1"}
PROJECT=${4:-"default"}
POLICIES_PATH=${5:-"policies"}


PARAM_OVERRIDES
PROJECT_LONG="${PROJECT}-psyclone"
STACK_NAME="${PROJECT_LONG}-${STAGE}"


TEMPLATE_EXT="template"
TEMPLATE_KEY="templates"
UPDATED_TEMPLATE_KEY="templates_updated"
ROOT_TEMPLATE="./${UPDATED_TEMPLATE_KEY}/turbine-master.${TEMPLATE_EXT}"
S3_PACKAGE_KEY="templates"


if [[ ! -z ${PROFILE} ]]; then
    # ${PROFILE} was given
    PROFILE_OPT=" --profile ${PROFILE}"
    echo ''
    echo "Using: '${PROFILE_OPT}'"
    # Create credential envars
    export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id ${PROFILE_OPT})
    export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key ${PROFILE_OPT})
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --output text --query 'Account' ${PROFILE_OPT} ${REGION_OPT})

DEPLOY_BUCKET="${PROJECT}-deploy-${AWS_ACCOUNT_ID}-${REGION}"

TURBINE_BUCKET="${DEPLOY_BUCKET}"
TURBINE_PREFIX="${STAGE}/"

LOAD_EXAMPLE_DAGS=False
LOAD_DEFAULT_CONS=False



PARAM_OVERRIDES="QSS3BucketName=${TURBINE_BUCKET} QSS3KeyPrefix=${TURBINE_PREFIX} LoadExampleDags=${LOAD_EXAMPLE_DAGS} LoadDefaultCons=${LOAD_DEFAULT_CONS} MinGroupSize=1"




export AWS_DEFAULT_REGION=${REGION}
aws configure set default.region ${AWS_DEFAULT_REGION}

check_for_error() {

    if [ "$1" -ne 0 ]; then
        echo ''
        echo "*********************"
        echo "** ERROR"
        echo "** $2"
        echo "*********************"
        echo ''
        exit $1
    fi
}

echo ''
echo "CREATING TEMPLATES..."

python3 update_yaml_templates.py "${TEMPLATE_KEY}" "${POLICIES_PATH}" "${UPDATED_TEMPLATE_KEY}" "${STAGE}"

# Create Bucket for lambda code and to store scripts for setting up airflow
aws s3 mb s3://${TURBINE_BUCKET} ${PROFILE_OPT} ${REGION_OPT}
# Zip and upload the lambda code ready for deploment
zip load_metric functions/load_metric.py
aws s3 cp load_metric.zip s3://${TURBINE_BUCKET}/${TURBINE_PREFIX}functions/package.zip ${PROFILE_OPT}
# Upload scripts used for airflow initialisation on EC2 machines
aws s3 cp scripts/ s3://${TURBINE_BUCKET}/${TURBINE_PREFIX}scripts --recursive ${PROFILE_OPT} > /dev/null

# upload vpc script
aws s3 cp submodules/quickstart-aws-vpc/templates/aws-vpc.template s3://${TURBINE_BUCKET}/${TURBINE_PREFIX}submodules/quickstart-aws-vpc/templates/aws-vpc.template ${PROFILE_OPT}

# Create deploy bucket if it doesn't already exist
aws s3 mb s3://${DEPLOY_BUCKET} ${PROFILE_OPT} ${REGION_OPT}
aws s3 cp ./${UPDATED_TEMPLATE_KEY}/ s3://${DEPLOY_BUCKET}/${TURBINE_PREFIX}${S3_PACKAGE_KEY}/ --recursive ${PROFILE_OPT}

check_for_error $? "Failed to upload templates"

# Deploy or update the AWS infrastructure
echo ''
echo "...CREATING/UPDATING CLOUDFORMATION STACKS..."
echo "aws cloudformation deploy --template-file ${ROOT_TEMPLATE} --s3-bucket ${DEPLOY_BUCKET} --s3-prefix ${UPDATED_TEMPLATE_KEY} --stack-name ${STACK_NAME} --parameter-overrides ${PARAM_OVERRIDES} --capabilities CAPABILITY_NAMED_IAM ${PROFILE_OPT} ${REGION_OPT}"
aws cloudformation deploy --template-file ${ROOT_TEMPLATE} --s3-bucket ${DEPLOY_BUCKET} --s3-prefix ${TURBINE_PREFIX}${UPDATED_TEMPLATE_KEY} --stack-name ${STACK_NAME} --parameter-overrides ${PARAM_OVERRIDES} --capabilities CAPABILITY_NAMED_IAM ${PROFILE_OPT} ${REGION_OPT}
check_for_error $? "Failed to deploy template"

