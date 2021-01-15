#!/bin/bash -e
find /airflow/logs/ -type f -mtime +"$REMOVE_LOGS_OLDER_THAN_X_DAYS" -name "*.log" -exec rm -rf {} \;