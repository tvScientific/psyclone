#!/bin/bash -e

. "$(dirname $0)/commons.setup.sh"

if [ "$TURBINE__CORE__LOAD_DEFAULTS" == "True" ]; then
    su -c '/usr/local/bin/airflow initdb' ec2-user
else
    su -c '/usr/local/bin/airflow upgradedb' ec2-user
fi

systemctl enable --now airflow-scheduler

mkdir /mnt/efs
FSPEC="${FILE_SYSTEM_ID}.efs.$AWS_REGION.amazonaws.com:/"
PARAMS="nfsvers=4.1,rsize=1048576,wsize=1048576"
PARAMS="$PARAMS,hard,timeo=600,retrans=2,noresvport"
echo "$FSPEC /mnt/efs nfs $PARAMS,_netdev 0 0" >> /etc/fstab
mount /mnt/efs && chown -R ec2-user: /mnt/efs

chown -R ec2-user /airflow/logs

if ! [ -z "${SMALL_QUEUE_NAME}" ]; then
    if [ "$CD_PENDING_DEPLOY" = "false" ]; then
        systemctl enable --now airflow-workerset-small
    else
        systemctl enable airflow-workerset-small
    fi
fi

cd_agent
