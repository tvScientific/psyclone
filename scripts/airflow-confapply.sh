#!/bin/bash -e
systemctl is-enabled --quiet airflow-scheduler &&\
    systemctl restart airflow-scheduler
systemctl is-enabled --quiet airflow-webserver &&\
    systemctl restart airflow-webserver
systemctl is-enabled --quiet airflow-workerset &&\
    systemctl restart airflow-workerset
systemctl is-enabled --quiet airflow-remove_worker_logs &&\
    systemctl restart airflow-remove_worker_logs
exit 0
