#!/usr/bin/env python3

"""
(c) Dativa 2019, all rights reserved
-----------------------------------------
This code is licensed under MIT license

Redistribution & use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
    this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.
    * Neither the name of the Dativa Limited nor the names of
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

from troposphere import Ref, Template, Join, Parameter, Sub
from troposphere import constants
from troposphere.cloudwatch import Dashboard

"""
Initialise logger
"""
logger = logging.getLogger("dativa.tools.aws.dashboard")


class DativaDashboardTemplate:  # need to subclass the generic base of templates here.

    def __init__(self, project_name, stage_name, source_path="./dashboards", template_path="./templates"):
        # Note: Module names should use '_' not '-' but some names cannot contain '_' so replace with dashes
        self._project = project_name
        self._dash_project = self._project.replace('_', '-')

        self._file_ext = 'json'
        self._stage_name = stage_name
        self._template_path = template_path
        source_file_unique = "{}/dashboard-{}.{}".format(source_path, self._stage_name, self._file_ext)
        source_file_template = "{}/dashboard-template.{}".format(source_path, self._file_ext)

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
            "SQSATaskQueueName",
            Description="Name of task SQS queue required",
            Type=constants.STRING,
        ))
        t.add_parameter(Parameter(
            "TurbineTaskStackName",
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
        # # Avoids issues with trying to parse out the format variables from string JSON, which has lots of { and } from
        # # Python string format parsing
        # for key, val in kwargs.items():
        #     str_dashboard = str_dashboard.replace("<" + key + ">", val)
        #     logger.info("Replacing {} with {}".format("<" + key + ">", val))
        # logger.info("Replacing {} with {}".format("<UniqueDashboard>", str(self.unique_dashboard)))
        # str_dashboard = str_dashboard.replace("<UniqueDashboard>", str(self.unique_dashboard))
        # logger.info("Finished, creating dashboard template")

        t.add_resource(Dashboard(
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
        """
        Deploy Dashboard
        """

        """
        Create the template
        """
        return self._save_template(template_name, t.to_json())

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
        outname = "{}_{}.{}".format(
            self._long_project,
            name,
            self._file_ext)

        with open(self._template_path + '/' + outname, 'w') as outfile:
            outfile.write(outstr)

        return outname
