#!/bin/bash -e
yum install -y jq
jsonvar() { jq -n --argjson doc "$1" -r "\$doc.$2"; }

IMDSv1="http://169.254.169.254/latest"
AWS_PARTITION=$(curl "$IMDSv1/meta-data/services/partition")
export AWS_PARTITION

IAM_ROLE=$(curl "$IMDSv1/meta-data/iam/security-credentials")
IAM_DOCUMENT=$(curl "$IMDSv1/meta-data/iam/security-credentials/$IAM_ROLE")
AWS_ACCESS_KEY_ID=$(jsonvar "$IAM_DOCUMENT" AccessKeyId)
AWS_SECRET_ACCESS_KEY=$(jsonvar "$IAM_DOCUMENT" SecretAccessKey)
AWS_SECURITY_TOKEN=$(jsonvar "$IAM_DOCUMENT" Token)
export IAM_ROLE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SECURITY_TOKEN

EC2_DOCUMENT=$(curl "$IMDSv1/dynamic/instance-identity/document")
AWS_REGION=$(jsonvar "$EC2_DOCUMENT" region)
AWS_DEFAULT_REGION=$(jsonvar "$EC2_DOCUMENT" region)
AWS_ACCOUNT_ID=$(jsonvar "$EC2_DOCUMENT" accountId)
EC2_INSTANCE_ID=$(jsonvar "$EC2_DOCUMENT" instanceId)
export AWS_DEFAULT_REGION AWS_REGION AWS_ACCOUNT_ID EC2_INSTANCE_ID

AUTO_SCALING_GROUP_NAME=$(aws cloudformation describe-stacks --stack-name "${AWS_STACK_NAME}" | jq '.Stacks[].Outputs[0] | select(.OutputKey|test("AutoScalingGroup")) | .OutputValue')
SHUTDOWN_LIFECYCLE_NAME=$(aws cloudformation describe-stacks --stack-name "${AWS_STACK_NAME}" | jq '.Stacks[].Outputs[] | select(.OutputKey|test("GracefulShutdownLifecycleHook")) | .OutputValue')
export AUTO_SCALING_GROUP_NAME
export SHUTDOWN_LIFECYCLE_NAME

yum install -y python3 python3-pip python3-wheel python3-devel

wget https://files.pythonhosted.org/packages/cb/28/91f26bd088ce8e22169032100d4260614fc3da435025ff389ef1d396a433/pip-20.2.4-py2.py3-none-any.whl
python3 -m pip install pip-20.2.4-py2.py3-none-any.whl

# We need to version-lock urllib3 since version 2 requires openssl 1.1.1,
# and yum only has openssl 1.0.1
pip3 install urllib3==1.26.15

# We need to version-lock importlib-metadata since celery conflicts with
# later versions of it
pip3 install importlib-metadata==4.13.0

# We need to version-lock wtforms since the >=3 has a breaking change
pip3 install wtforms==2.3.3

pip3 install marshmallow-sqlalchemy==0.25.0
pip3 install awscurl
EC2_HOST_IDENTIFIER="arn:$AWS_PARTITION:ec2:$AWS_REGION:$AWS_ACCOUNT_ID"
EC2_HOST_IDENTIFIER="$EC2_HOST_IDENTIFIER:instance/$EC2_INSTANCE_ID"
CD_COMMAND=$(/usr/local/bin/awscurl -X POST \
    --service codedeploy-commands \
    "https://codedeploy-commands.$AWS_REGION.amazonaws.com" \
    -H "X-AMZ-TARGET: CodeDeployCommandService_v20141006.PollHostCommand" \
    -H "Content-Type: application/x-amz-json-1.1" \
    -d "{\"HostIdentifier\": \"$EC2_HOST_IDENTIFIER\"}")
if [ "$CD_COMMAND" = "" ] || [ "$CD_COMMAND" = "b'{}'" ]
then CD_PENDING_DEPLOY="false"
else CD_PENDING_DEPLOY="true"
fi
export CD_PENDING_DEPLOY

DB_SECRETS=$(aws secretsmanager \
    get-secret-value --secret-id "$DB_SECRETS_ARN")
DB_ENGINE=$(jsonvar "$DB_SECRETS" "SecretString | fromjson.engine")
DB_USER=$(jsonvar "$DB_SECRETS" "SecretString | fromjson.username")
DB_PASS=$(jsonvar "$DB_SECRETS" "SecretString | fromjson.password")
DB_HOST=$(jsonvar "$DB_SECRETS" "SecretString | fromjson.host")
DB_DBNAME=$(jsonvar "$DB_SECRETS" "SecretString | fromjson.dbname")
DB_PORT=$(jsonvar "$DB_SECRETS" "SecretString | fromjson.port")
DATABASE_URI="$DB_ENGINE://$DB_USER:$DB_PASS@$DB_HOST:$DB_PORT/$DB_DBNAME"
export DATABASE_URI

yum install -y python3
pip3 install cryptography
FERNET_KEY=$(python3 -c "if True:#
    from base64 import urlsafe_b64encode
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),length=32,iterations=100000,
		backend=default_backend(),salt=b'${FERNET_SALT//\'/\\\'}',
    )
    key = kdf.derive(b'${DB_PASS_ESC//\'/\\\'}')
    key_encoded = urlsafe_b64encode(key)
    print(key_encoded.decode('utf8'))")
export FERNET_KEY


FILES=$(dirname "$0")
find "$FILES" -type f -iname "*.sh" -exec chmod +x {} \;
envreplace() { CONTENT=$(envsubst <"$1"); echo "$CONTENT" >"$1"; }

mkdir -p /etc/cfn/hooks.d
cp "$FILES"/systemd/cfn-hup.service /lib/systemd/system/
cp "$FILES"/systemd/cfn-hup.conf /etc/cfn/cfn-hup.conf
cp "$FILES"/systemd/cfn-auto-reloader.conf /etc/cfn/hooks.d/cfn-auto-reloader.conf
envreplace /etc/cfn/cfn-hup.conf
envreplace /etc/cfn/hooks.d/cfn-auto-reloader.conf

mkdir /run/airflow && chown -R ec2-user: /run/airflow
cp "$FILES"/systemd/airflow-*.{path,timer,service} /lib/systemd/system/
cp "$FILES"/systemd/airflow.env /etc/sysconfig/airflow.env
cp "$FILES"/systemd/airflow-workerset-small.env /etc/sysconfig/airflow-workerset-small.env
cp "$FILES"/systemd/airflow.conf /usr/lib/tmpfiles.d/airflow.conf
envreplace /etc/sysconfig/airflow.env

echo "SMALL_QUEUE_NAME is ${SMALL_QUEUE_NAME}"

envreplace /etc/sysconfig/airflow-workerset-small.env
envreplace /usr/lib/systemd/system/airflow-workerset-small.service

mapfile -t AIRFLOW_ENVS < /etc/sysconfig/airflow.env
export "${AIRFLOW_ENVS[@]}"

yum install -y gcc libcurl-devel openssl-devel
export PYCURL_SSL_LIBRARY=openssl
pip3 install "apache-airflow[celery,postgres,s3,crypto,google_auth]==1.10.10" "celery[sqs]==4.4.7"
pip3 install SQLAlchemy==1.3.23
pip3 install WTForms==2.3.3
pip3 install itsdangerous==2.0.1
pip3 install Flask==1.1.2
pip3 install MarkupSafe==2.0.1
mkdir "$AIRFLOW_HOME" && chown -R ec2-user: "$AIRFLOW_HOME"

systemctl enable --now cfn-hup.service

# add this to script
export PATH=/usr/local/bin:$PATH
yum -y --security update
yum -y install jq
yum -y install awslogs
yum -y install aws-cli

cd_agent() {
    yum install -y ruby
    wget "https://aws-codedeploy-$AWS_REGION.s3.amazonaws.com/latest/install"
    chmod +x ./install
    ./install auto
}
