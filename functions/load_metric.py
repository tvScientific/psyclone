import datetime
import logging
import os

import boto3

CW = boto3.client("cloudwatch")
logging.getLogger().setLevel(os.environ.get("LOGLEVEL", logging.INFO))


def handler(_event, _context):
    """
    https://github.com/villasv/aws-airflow-stack/wiki/Cluster-Load-Metric-Rationale
    """
    logging.debug("environment variables:\n %s", os.environ)

    timestamp = datetime.datetime.now(datetime.timezone.utc)
    timestamp = timestamp - datetime.timedelta(
        minutes=2,
        seconds=timestamp.second,
        microseconds=timestamp.microsecond,
    )
    # We jump 2 minutes back because that's how far behind the aws metrics we're accessing are

    logging.info("evaluating at [%s]", timestamp)

    metrics = get_metrics(timestamp)
    logging.debug("available metrics: %s", metrics)

    messages = metrics["maxANOMV"]
    requests = metrics["sumNOER"]
    machines = metrics["avgGISI"]
    logging.info("ANOMV=%s NOER=%s GISI=%s", messages, requests, machines)
    average_polling_freq_per_minute = 5.5
    """ average_polling_freq_per_minute is determined by observing the aws sqs metric of empty receives it is currently
    5 or 6 per minute so we take an average of 5.5
    """

    if machines > 0:
        load = 1.0 - requests / (machines * average_polling_freq_per_minute)
    elif messages > 0:
        load = 1.0
    else:
        return

    logging.info("L=%s", load)
    put_metric(timestamp, load)


def get_metrics(timestamp):
    queue = os.environ["QueueName"]
    group = os.environ["GroupName"]
    response = CW.get_metric_data(
        StartTime=timestamp,
        EndTime=timestamp + datetime.timedelta(minutes=1),
        ScanBy="TimestampAscending",
        MetricDataQueries=[
            {
                "Id": "maxANOMV",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SQS",
                        "MetricName": "ApproximateNumberOfMessagesVisible",
                        "Dimensions": [{"Name": "QueueName", "Value": f"{queue}"}],
                    },
                    "Period": 60,
                    "Stat": "Maximum",
                    "Unit": "Count",
                },
            },
            {
                "Id": "sumNOER",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SQS",
                        "MetricName": "NumberOfEmptyReceives",
                        "Dimensions": [{"Name": "QueueName", "Value": f"{queue}"}],
                    },
                    "Period": 60,
                    "Stat": "Sum",
                    "Unit": "Count",
                },
            },
            {
                "Id": "avgGISI",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/AutoScaling",
                        "MetricName": "GroupInServiceInstances",
                        "Dimensions": [
                            {"Name": "AutoScalingGroupName", "Value": f"{group}"}
                        ],
                    },
                    "Period": 60,
                    "Stat": "Average",
                    "Unit": "None",
                },
            },
        ],
    )
    return {
        m["Id"]: dict(zip(m["Timestamps"], m["Values"]))[timestamp]
        for m in response["MetricDataResults"]
    }


def put_metric(time, value):
    CW.put_metric_data(
        Namespace="Turbine",
        MetricData=[
            {
                "MetricName": "ClusterLoad",
                "Dimensions": [{"Name": "StackName", "Value": os.environ["StackName"]}],
                "Timestamp": time,
                "Value": value,
                "Unit": "None",
            }
        ],
    )
