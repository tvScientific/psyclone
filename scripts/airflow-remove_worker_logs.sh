#!/bin/bash -e
find /airflow/logs/ -type f -name "*.log" -exec rm -rf {} \;