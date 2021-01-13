#!/bin/bash -e
find /airflow/logs/ -type f -atime +"$REMOVE_LOGS_OLDER_THAN_X_DAYS" -name "*.log" -exec rm -rf {} \;