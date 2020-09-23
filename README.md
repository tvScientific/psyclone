# Dativa
This is a work in progress, both the code and readme are being updated and actively developed so somethings may not be in the neatest format for the time being.

## Deployment

As part of the dativa deployment a number of things have been added to utilise these additions the project deployment script can be called.

### Usefull additions
1. Add additional policies
2. Deploy additional templates under the master level template

### Deployment instructions
The deployment script takes as input the location of any additional policies and additional template. 

When specifying policies it should be done in the same format as what's in the policies folder in this project (included as an example) 
and the bash should provide an absolute path to the policies directory.

When specifying an additional template the full path to the top level template should be passed in, any further templates should be deployed from this
as nested and uploaded as part of the project level deployment.

The deployment script will copy all files in the directory of the additional template into templates_updated/additional_templates however it will be uploaded to the 
deployment s3 under templates/additional_templates, any nested templates should be aware of this and look to point to the QSS3Bucket/QSS3Prefix/templates/additional_templates.

### Changes to templates
Some small changes to the base templates and files from the original fork have had to be made:

1. scripts/systemd/airflow-webserver.service -- removal of 2 lines, specifying user and user-group this allows airflow to run as root on the webserver 
2. templates/turbine-master.template -- Change to MinValue of WebserverPort down to 0 so we can set to 80 needed for websever security
3. templates/turbine-cluster.template -- Change to MinValue of WebserverPort down to 0 so we can set to 80 needed for websever security
4. templates/turbine-webserver.template -- Change to MinValue of WebserverPort down to 0 so we can set to 80 needed for websever security

### List of params that can be overridden
SchedulerInstanceType
WebserverInstanceType
WorkerInstanceType
MinGroupSize
MaxGroupSize
ShrinkThreshold
GrowthThreshold
LoadExampleDags
LoadDefaultCons
WebServerPort

### Authentication and creating users

Password authentication is enabled for the airflow webserver. When a stack is deployed, 
no users are initialised alongside it. Adding the initial user requires you to use SSM 
to access the webserver, you must then set up a connection to the user database and use 
the airflow python interface. 

To connect to the airflow webserver, go to EC2 console and find the appropriate webserver 
for the desired stack. Select it and click on `Connect` then choose `Session Manager` 
as your connection method, click on connect and you will be taken to a terminal view in 
the EC2. You can now set up environment used by airflow , this is done by finding a file
on the EC2 which contains the required environment variables and exporting them in 
the current session.
  
DO NOT EDIT THE CONTENT OF THE FILE - this would break the webserver
```shell script
vi /etc/sysconfig/airflow.env
```
Example of the file contents
```shell script
AWS_DEFAULT_REGION=eu-west-1
AIRFLOW_HOME=/airflow
AIRFLOW__CORE__EXECUTOR=CeleryExecutor
...
```
Export every line in this script to an environment variable. This can be done with a command such as:
 ```shell script
export AWS_DEFAULT_REGION=eu-west-1
export AIRFLOW_HOME=/airflow
export AIRFLOW__CORE__EXECUTOR=CeleryExecutor
...
```
You can then use the airflow CLI interface to add a user 
(please use a better password, airflow does not enforce a password policy).  

```shell script
airflow create_user -u admin -e admin@example.com -f admin -l admin -p password -r Admin
```

For this change to propagate to the webserver, you will need to restart it. For that run the following script. 
This must be run as root as the webserver is run as the root user. 
```shell script
sudo su
systemctl stop airflow-webserver
sleep 30
systemctl start airflow-webserver
```                           
You can now go to the airflow link to log in with the username and password outlined above. 
This will give you access to the airflow webserver. 

If you get an 'Invalid Login' message, it may mean that not all lines from the airflow.env file were set, 
please check and try again. If a given user is created by accident, you can delete it with the following command
```shell script
airflow delete_user -u username
```

### Below this is the original turbine readme, left as is unedited

<img src=".github/img/logo.png" align="right" width="25%" />

# Turbine [![GitHub Release](https://img.shields.io/github/release/villasv/aws-airflow-stack.svg?style=flat-square&logo=github)](https://github.com/villasv/aws-airflow-stack/releases/latest) [![Build Status](https://img.shields.io/github/workflow/status/villasv/aws-airflow-stack/Stack%20Release%20Pipeline?style=flat-square&logo=github&logoColor=white&label=build)](https://github.com/villasv/aws-airflow-stack/actions?query=workflow%3A%22Stack+Release+Pipeline%22+branch%3Amaster) [![CFN Deploy](https://img.shields.io/badge/CFN-deploy-green.svg?style=flat-square&logo=amazon-aws)](#get-it-working)

Turbine is the set of bare metals behind a simple yet complete and efficient
Airflow setup.

The project is intended to be easily deployed, making it great for testing,
demos and showcasing Airflow solutions. It is also expected to be easily
tinkered with, allowing it to be used in real production environments with
little extra effort. Deploy in a few clicks, personalize in a few fields,
configure in a few commands.

## Overview

![stack diagram](/.github/img/stack-diagram.png)

The stack is composed mainly of three services: the Airflow web server, the
Airflow scheduler, and the Airflow worker. Supporting resources include an RDS
to host the Airflow metadata database, an SQS to be used as broker backend, S3
buckets for logs and deployment bundles, an EFS to serve as shared directory,
and a custom CloudWatch metric measured by a timed AWS Lambda. All other
resources are the usual boilerplate to keep the wind blowing.

### Deployment and File Sharing

The deployment process through CodeDeploy is very flexible and can be tailored
for each project structure, the only invariant being the Airflow home directory
at `/airflow`. It ensures that every Airflow process has the same files and can
upgraded gracefully, but most importantly makes deployments really fast and easy
to begin with.

There's also an EFS shared directory mounted at at `/mnt/efs`, which can be
useful for staging files potentially used by workers on different machines and
other synchronization scenarios commonly found in ETL/Big Data applications. It
facilitates migrating legacy workloads not ready for running on distributed
workers.

### Workers and Auto Scaling

The stack includes an estimate of the cluster load average made by analyzing the
amount of failed attempts to retrieve a task from the queue. The metric
objective is to measure if the cluster is correctly sized for the influx of
tasks. Worker instances have lifecycle hooks promoting a graceful shutdown,
waiting for tasks completion when terminating.

The goal of the auto scaling feature is to respond to changes in queue load,
which could mean an idle cluster becoming active or a busy cluster becoming
idle, the start/end of a backfill, many DAGs with similar schedules hitting
their due time, DAGs that branch to many parallel operators. **Scaling in
response to machine resources like facing CPU intensive tasks is not the goal**;
the latter is a very advanced scenario and would be best handled by Celery's own
scaling mechanism or offloading the computation to another system (like Spark or
Kubernetes) and use Airflow only for orchestration.

## Get It Working

### 0. Prerequisites

- Configured AWS CLI for deploying your own files
  [(Guide)](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)

### 1. Deploy the stack

Create a new stack using the latest template definition at
[`templates/turbine-master.template`](/templates/turbine-master.template). The
following button will deploy the stack available in this project's `master`
branch (defaults to your last used region):

[![Launch](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/images/cloudformation-launch-stack-button.png)](https://console.aws.amazon.com/cloudformation/home#/stacks/new?templateURL=https://turbine-quickstart.s3.amazonaws.com/quickstart-turbine-airflow/templates/turbine-master.template)

The stack resources take around 15 minutes to create, while the airflow
installation and bootstrap another 3 to 5 minutes. After that you can already
access the Airflow UI and deploy your own Airflow DAGs.

### 2. Upstream your files

The only requirement is that you configure the deployment to copy your Airflow
home directory to `/airflow`. After crafting your `appspec.yml`, you can use the
AWS CLI to deploy your project.

For convenience, you can use this [`Makefile`](/examples/project/Makefile) to
handle the packaging, upload and deployment commands. A minimal working example
of an Airflow project to deploy can be found at
[`examples/project/airflow`](/examples/project/airflow).

If you follow this blueprint, a deployment is as simple as:

```bash
make deploy stack-name=yourcoolstackname
```

## Maintenance and Operation

Sometimes the cluster operators will want to perform some additional setup,
debug or just inspect the Airflow services and database. The stack is designed
to minimize this need, but just in case it also offers decent internal tooling
for those scenarios.

### Using Systems Manager Sessions

Instead of the usual SSH procedure, this stack encourages the use of AWS Systems
Manager Sessions for increased security and auditing capabilities. You can still
use the CLI after a bit more configuration and not having to expose your
instances or creating bastion instances is worth the effort. You can read more
about it in the Session Manager
[docs](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html).

### Running Airflow commands

The environment variables used by the Airflow service are not immediately
available in the shell. Before running Airflow commands, you need to load the
Airflow configuration:

```bash
$ export $(xargs </etc/sysconfig/airflow.env)
$ airflow list_dags
```

### Inspecting service logs

The Airflow service runs under `systemd`, so logs are available through
`journalctl`. Most often used arguments include the `--follow` to keep the logs
coming, or the `--no-pager` to directly dump the text lines, but it offers [much
more](https://www.freedesktop.org/software/systemd/man/journalctl.html).

```bash
$ sudo journalctl -u airflow -n 50
```


## FAQ

1. Why does auto scaling takes so long to kick in?

    AWS doesn't provide minute-level granularity on SQS metrics, only 5 minute
    aggregates. Also, CloudWatch stamps aggregate metrics with their initial
    timestamp, meaning that the latest stable SQS metrics are from 10 minutes in
    the past. This is why the load metric is always 5~10 minutes delayed. To
    avoid oscillating allocations, the alarm action has a 10 minutes cooldown.

2. Why can't I stop running tasks by terminating all workers?

    Workers have lifecycle hooks that make sure to wait for Celery to finish its
    tasks before allowing EC2 to terminate that instance (except maybe for Spot
    Instances going out of capacity). If you want to kill running tasks, you
    will need to SSH into worker instances and stop the airflow service
    forcefully.

3. Is there any documentation around the architectural decisions?

    Yes, most of them should be available in the project's GitHub
    [Wiki](https://github.com/villasv/aws-airflow-stack/wiki). It doesn't mean
    those decisions are final, but reading them beforehand will help formulating
    new proposals.

## Contributing

>This project aims to be constantly evolving with up to date tooling and newer
>AWS features, as well as improving its design qualities and maintainability.
>Requests for Enhancement should be abundant and anyone is welcome to pick them
>up.
>
>Stacks can get quite opinionated. If you have a divergent fork, you may open a
>Request for Comments and we will index it. Hopefully this will help to build a
>diverse set of possible deployment models for various production needs.

See the [contribution guidelines](/CONTRIBUTING.md) for details.

You may also want to take a look at the [Citizen Code of
Conduct](/CODE_OF_CONDUCT.md).

Did this project help you? Consider buying me a cup of coffee ;-)

[![Buy me a coffee!](https://www.buymeacoffee.com/assets/img/custom_images/white_img.png)](https://www.buymeacoffee.com/villasv)

## Licensing

> MIT License
>
> Copyright (c) 2017 Victor Villas

See the [license file](/LICENSE) for details.
