#!/usr/bin/env python3

"""
(c) Deductive 2019, all rights reserved
-----------------------------------------
This code is licensed under MIT license

Redistribution & use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
    this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.
    * Neither the name of the Deductive Limited nor the names of
    its contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import json
import logging
import os
import random
import string

from troposphere import Ref, Template, Join, Parameter, Sub
from troposphere import constants
from troposphere import cloudwatch
from troposphere import sns

"""
Initialise logger
"""
logger = logging.getLogger("deductive.tools.aws.dashboard")


class DativaDashboardTemplate:

    @staticmethod
    def _random_generator(size=3, chars=string.ascii_lowercase):
        return ''.join(random.choice(chars) for x in range(size)).title()

    def __init__(self, project_name, stage_name, source_path="./dashboards", template_path="./templates"):
        """
        class to read in and generate the
        :param project_name: labels the resulting dashboard
        :param stage_name: stage type being deployed, e.g. PROD, DEV, etc.
        :param source_path: location where json is stored
        :param template_path: path to write the templates to -
        """
        # Note: Module names should use '_' not '-' but some names cannot contain '_' so replace with dashes
        self._project = project_name
        self._dash_project = self._project.replace('_', '-')
        self._alphanum_project = self._project.replace('_', '').replace('-', '')

        self._file_ext = 'json'
        self._file_ext_output = 'template'
        self._stage_name = stage_name
        self._stage_name_alphanum = stage_name.title().replace("_", "").replace("-", "")
        self._template_path = template_path
        source_file_unique = "{}/dashboard-{}.{}".format(source_path, self._stage_name, self._file_ext)
        source_file_template = "{}/dashboard-template.{}".format(source_path, self._file_ext)
        self._random_ascii = self._random_generator()

        # Pick up appropriate dashboard if it exists, else use the generic template
        if self.does_unique_dashboard_file_exist(source_file_unique):
            self.source_file_path = source_file_unique
            self.dashboard_source = self._load_json(source_file_unique)
            self.unique_dashboard = True
        else:
            self.source_file_path = source_file_template
            self.dashboard_source = self._load_json(source_file_template)
            self.unique_dashboard = False
        logger.info("Using template with path {}".format(self.source_file_path))

        self._warning_widget = "{}/warning-widget.{}".format(source_path, self._file_ext)
        self._expected_kwargs = [
            'SQSTaskQueueName', 'TurbineStackName',
            'EC2AutoScalingGroupName', 'EC2AutoScalingGroupNameWebserver', 'EC2AutoScalingGroupNameWorker',
        ]

    def generate_template(self, **kwargs):
        """
        will create a template in the instance template path
        :param kwargs: must include values found in self._expected_kwargs
        :return:
        """
        missing_kwargs = [kwarg for kwarg in self._expected_kwargs if kwarg not in self._expected_kwargs]
        if missing_kwargs:
            raise ValueError("Following kwargs were not provided when calling .generate_template() method of"
                             " Dashboard class {}".format(str(missing_kwargs)))
        """
        Create Dashboard template
        """
        ecs_template = self._generate_dashboard_template(**kwargs)

        logger.info("")
        logger.info("GENERATED: {}".format(ecs_template))

        return ecs_template

    @staticmethod
    def does_unique_dashboard_file_exist(path_to_unique):

        return os.path.exists(path_to_unique) and os.path.isfile(path_to_unique)

    def _generate_dashboard_template(self, **kwargs):

        """
        Generate Dashboard template
        """
        template_name = 'dashboard'

        t = Template()

        t.set_description("AWS CloudFormation Template: '{}'".format(self.source_file_path))

        """
        Stack Parameters
        """
        t.add_parameter(Parameter(
            "DeploymentStage",
            Description="Name of deployment stage required",
            Type=constants.STRING,
        ))
        t.add_parameter(Parameter(
            "SQSTaskQueueName",
            Description="Name of task SQS queue required",
            Type=constants.STRING,
        ))
        t.add_parameter(Parameter(
            "TurbineStackName",
            Description="Name of Turbine Stack required",
            Type=constants.STRING,
        ))
        t.add_parameter(Parameter(
            "EC2AutoScalingGroupName",
            Description="Name of Scheduler stack Auto Scaling group required",
            Type=constants.STRING,
        ))
        t.add_parameter(Parameter(
            "EC2AutoScalingGroupNameWorker",
            Description="Name of worker stack Auto Scaling group required",
            Type=constants.STRING,
        ))
        t.add_parameter(Parameter(
            "EC2AutoScalingGroupNameWebserver",
            Description="Name of webserver stack Auto Scaling grouprequired",
            Type=constants.STRING,
        ))
        dashboard_source = self.dashboard_source

        # Check if warning widget is already part of the dashboard, if not append it
        if 'This dashboard is automatically deployed by CloudFormation' not in json.dumps(dashboard_source):
            warning_widget = self._load_json(self._warning_widget)
            warning_widget = json.loads(json.dumps(warning_widget))
            warning_widget['y'] = self._find_dashboard_bottom(dashboard_source)
            dashboard_source['widgets'].append(warning_widget)

        str_dashboard = json.dumps(dashboard_source)
        logger.info("Replacing values with custom delimiters in Python...")

        t.add_resource(cloudwatch.Dashboard(
            self._project + "Dashboard",
            DashboardName=Join("-", [
                self._dash_project,
                "dashboard",
                Ref('DeploymentStage'),
                Ref('AWS::Region'),
                self._random_ascii,
            ]),
            DashboardBody=Sub(str_dashboard)
        ))

        self.add_instance_count_alarms(t)

        return self._save_template(template_name, t.to_yaml())

    def add_instance_count_alarms(self, t):
        """ adds alarms in place to template and an sns topic for the alarm"""

        # Add SNS topic to alert in case of failure
        sns_alarm_resource = "{}{}PsycloneCloudWatchAlarmTopic".format(
            self._alphanum_project, self._stage_name_alphanum)
        sns_alarm_topic_name = Join("-", [sns_alarm_resource, Ref("DeploymentStage")])
        t.add_resource(sns.Topic(sns_alarm_resource, DisplayName=sns_alarm_topic_name, TopicName=sns_alarm_topic_name))

        # Add alarms, define shared properties first
        period_mins = 1     # Smallest period that is supported by chosen AWS metric
        range_low = 1
        alarm_properties = dict(
            Period=period_mins * 60,
            Statistic="Minimum",
            AlarmActions=[Ref(sns_alarm_resource)],
            # OKActions=[Ref(sns_alarm_resource)],
            EvaluationPeriods="1",
            Namespace="AWS/AutoScaling",
            MetricName="GroupTotalInstances",
            TreatMissingData="breaching",
            ComparisonOperator="LessThanThreshold",
            Threshold=range_low,
        )

        metric_dim_webserver = cloudwatch.MetricDimension(
            Name="AutoScalingGroupName",
            Value=Ref("EC2AutoScalingGroupNameWebserver")
        )
        alarm_name_no_webserver = "{}NoPsycloneWebserverInstances".format(self._stage_name_alphanum)
        t.add_resource(
            cloudwatch.Alarm(
                alarm_name_no_webserver,
                AlarmName=Join("-", [alarm_name_no_webserver, Ref("DeploymentStage")]),
                AlarmDescription="No psyclone webserver instances for {}".format(self._stage_name),
                Dimensions=[metric_dim_webserver],
                **alarm_properties
            )
        )
        metric_dim_scheduler = cloudwatch.MetricDimension(
            Name="AutoScalingGroupName",
            Value=Ref("EC2AutoScalingGroupName")
        )
        alarm_name_no_scheduler = "{}NoPsycloneSchedulerInstances".format(self._stage_name_alphanum)
        t.add_resource(
            cloudwatch.Alarm(
                alarm_name_no_scheduler,
                AlarmName=Join("-", [alarm_name_no_scheduler, Ref("DeploymentStage")]),
                AlarmDescription="No psyclone scheduler instances for {}".format(self._stage_name),
                Dimensions=[metric_dim_scheduler],
                **alarm_properties
            )
        )
        # return t

    def _find_dashboard_bottom(self, dashboard_source):

        # Iterate the widgets to find the bottom one
        ypos = 0
        for widget in dashboard_source['widgets']:
            bottom = widget['y'] + widget['height']
            if bottom > ypos:
                ypos = bottom
        return ypos

    def _load_json(self, inpath):
        with open(inpath) as infile:
            doc = infile.read()
        return json.loads(doc)

    def _save_template(self, name, outstr):
        outname = "{}{}.{}".format(
            self._project,
            name,
            self._file_ext_output)

        with open(self._template_path + '/' + outname, 'w') as outfile:
            outfile.write(outstr)

        return outname
