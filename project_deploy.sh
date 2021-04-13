#!/bin/bash

# (c) Dativa 2019, all rights reserved

STAGE=${1:-"TEST"}
PROFILE=${2:-""}
REGION=${3:-"us-east-1"}
PROJECT=${4:-"default"}
ADDITIONAL_TEMPLATE_PATH=${5:-""}
VPC_TEMPLATE_PATH=${6:-""}

STAGE_LWR=$(echo "$STAGE" | tr '[:upper:]' '[:lower:]')
PROJECT_LONG="${PROJECT}-psyclone"
STACK_NAME="${PROJECT_LONG}-${STAGE}"

TEMPLATE_EXT="template"
UPDATED_TEMPLATE_KEY="templates_updated"
ROOT_TEMPLATE="./${UPDATED_TEMPLATE_KEY}/turbine-master.${TEMPLATE_EXT}"
S3_PACKAGE_KEY="templates"

if [[ ! -z ${PROFILE} ]]; then
    PROFILE_OPT=" --profile ${PROFILE}"
    echo ''
    echo "Using: '${PROFILE_OPT}'"
    # Create credential envars
    export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id ${PROFILE_OPT})
    export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key ${PROFILE_OPT})
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --output text --query 'Account' ${PROFILE_OPT} ${REGION_OPT})

DEPLOY_BUCKET="${PROJECT}-deploy-${AWS_ACCOUNT_ID}-${REGION}"

DEPLOY_BUCKET="${DEPLOY_BUCKET}"
TURBINE_PREFIX="${STAGE}/"

PARAM_OVERRIDES="${PARAM_OVERRIDES} QSS3BucketName=${DEPLOY_BUCKET} QSS3KeyPrefix=${TURBINE_PREFIX}"

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
echo "PACKAGING TEMPLATES..."
# If there is an additional template copy into templates_updated folder so it is deployed with the rest of the templates
if [[ ! -z "${ADDITIONAL_TEMPLATE_PATH}" ]]; then
    TEMPLATE_NAME=$(basename ${ADDITIONAL_TEMPLATE_PATH})
    PACKAGED_TEMPLATE_DIR="./templates_updated/additional_templates"
    rm -rf "${PACKAGED_TEMPLATE_DIR}"
    mkdir "${PACKAGED_TEMPLATE_DIR}"
    for TEMPLATE_PATH in ${ADDITIONAL_TEMPLATE_PATH}*.template; do
        TEMPLATE_NAME=$(basename "${TEMPLATE_PATH}")
        echo "run packaging on  ${TEMPLATE_NAME} ${TEMPLATE_PATH} to ${PACKAGED_TEMPLATE_DIR}/${TEMPLATE_NAME} $(pwd)"
        aws cloudformation package --template-file ${ADDITIONAL_TEMPLATE_PATH}/${TEMPLATE_NAME} --s3-bucket ${DEPLOY_BUCKET} --s3-prefix ${S3_PACKAGE_KEY} --output-template-file "${PACKAGED_TEMPLATE_DIR}/${TEMPLATE_NAME}" ${PROFILE_OPT} ${REGION_OPT}
    done
fi

# Create Bucket for lambda code and to store scripts for setting up airflow
aws s3 mb s3://${DEPLOY_BUCKET} ${PROFILE_OPT} ${REGION_OPT}
# Zip and upload the lambda code ready for deploment
zip -j load_metric functions/load_metric.py
aws s3 cp load_metric.zip s3://${DEPLOY_BUCKET}/${TURBINE_PREFIX}functions/package.zip ${PROFILE_OPT}
# Upload scripts used for airflow initialisation on EC2 machines
echo "UPLOADING SCRIPTS HERE"
aws s3 cp scripts/ s3://${DEPLOY_BUCKET}/${TURBINE_PREFIX}scripts --recursive ${PROFILE_OPT}
echo "FINISHED UPLOADING SCRIPTS HERE"

# upload vpc script
if [[ -z "${VPC_TEMPLATE_PATH}" ]]; then
    # No need to take any action - pre-made VPC template to use
    pass
else
    VPC_TEMPLATE_PATH="./templates_updated/vpc_template.template"
    python generate_vpc.py ${PROJECT_LONG} ${PROJECT} ${REGION} ${STAGE} ${VPC_TEMPLATE_PATH} || exit
fi
aws s3 cp ${VPC_TEMPLATE_PATH} s3://${DEPLOY_BUCKET}/${TURBINE_PREFIX}submodules/quickstart-aws-vpc/templates/aws-vpc.template ${PROFILE_OPT}

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

if [[ $STAGE_LWR == *"stag"* ]] || [[ $STAGE_LWR == *"prod"* ]]; then
    aws cloudformation update-termination-protection --enable-termination-protection --stack-name $STACK_NAME $PROFILE_OPT $REGION_OPT
    check_for_error $? "Failed to update termination protection"
fi
