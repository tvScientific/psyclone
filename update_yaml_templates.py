import configparser
import glob
import json
import logging
import os
import random
import string
import sys

from awacs.aws import PolicyDocument, Statement, Principal, Action, Condition, StringEquals
from cfn_tools import load_yaml, dump_yaml
from troposphere import Ref, Parameter, Template, Output, Join, GetAtt, Split, NoValue, AccountId
from troposphere import cloudfront
from troposphere import ec2
from troposphere import elasticloadbalancingv2
from troposphere import route53
from troposphere import s3

from psyclone.dashboards.dativa_dashboard_template import DativaDashboardTemplate

logger = logging.getLogger(__name__)
stdout = logging.StreamHandler(sys.stdout)
stdout.setFormatter(logging.Formatter('%(message)s'))
stdout.setLevel(logging.INFO)
logger.addHandler(stdout)
logger.setLevel(logging.INFO)


class Labels:
    security_group_attach_to_lb = "SecurityGroupIDsToAttachToLoadBalancer"
    vpc_id_for_sgs = "VpcId"
    target_group_arns_for_autoscaling = "TargetGroupNameForAutoscaling"
    subnet_ids = "SubnetIDs"
    master_label = "master"
    cluster_label = "cluster"
    workerset_label = "workerset"
    scheduler_label = "scheduler"
    webserver_label = "webserver"
    vpc_s3_endpoint_id = "VPCS3EndpointID"


class UpdateTemplates:
    ALLOWED_STAGES = ["PROD", "STAG", "DEV", "DEV-1", "DEV-2", "DEV-3"]
    PRODLIKE_STACKS = ["PROD", "STAG"]
    DOMAIN = "psyclone.pro"
    STAGE_NAMES_AND_CONFIGS = ()

    @staticmethod
    def _random_generator(size=3, chars=string.ascii_lowercase):
        return ''.join(random.choice(chars) for x in range(size)).title()

    # better names
    def __init__(self, templates_path, policies_base_path, updated_templates_path, stage_name, project_name,
                 region=None, load_balancer=False):
        self.templates_path = templates_path
        self.policies_base_path = policies_base_path
        self.updated_templates_path = updated_templates_path
        self.stage_name = stage_name
        self.template_list = [
            Labels.master_label,
            Labels.cluster_label,
            Labels.webserver_label,
            Labels.scheduler_label,
            Labels.workerset_label
        ]
        self.templates_dict = dict()
        self.region = region
        self._load_templates()
        self.random_string = self._random_generator()
        self.project_name = project_name
        if 'PROD' in stage_name:
            self.add_cloudtrail()
        if load_balancer:
            if region is None:
                raise ValueError('Region is required to deploy a load balancer')
            loadbalancer_class = LoadBalancerTemplate(
                stage_name, region, self.DOMAIN, self.random_string, project_name, self.PRODLIKE_STACKS,
                self.ALLOWED_STAGES)
            loadbalancer_and_routing = loadbalancer_class.loadbalancer_and_routing()
            cfs_path = loadbalancer_class.write_to_file("loadbalancer-and-routing-stack",
                                                        loadbalancer_and_routing)
            self.add_template(
                cfs_path,
                {
                    Labels.vpc_id_for_sgs: {"Fn::GetAtt": ["VPCStack", "Outputs.VPCID"]},
                    Labels.vpc_s3_endpoint_id: {"Fn::GetAtt": ["VPCStack", "Outputs.S3VPCEndpoint"]},
                    Labels.subnet_ids: Join(
                        ",",
                        [
                            GetAtt('VPCStack', 'Outputs.PublicSubnet1ID'),
                            GetAtt('VPCStack', 'Outputs.PublicSubnet2ID'),
                        ]
                    ).to_dict()
                },
            )
            self.update_webserver()

    def update_webserver(self):
        """ to_include_loadbalancer_and_disable_access """
        self.templates_dict[Labels.master_label]['Resources']['TurbineCluster']['Properties']['Parameters'].update(
            {Labels.target_group_arns_for_autoscaling: {
                "Fn::GetAtt": ["LoadbalancerAndRoutingStack", "Outputs." + Labels.target_group_arns_for_autoscaling]
            }}
        )
        webserver_label = Labels.webserver_label
        self.templates_dict[webserver_label]['Parameters'].update(
            {
                Labels.target_group_arns_for_autoscaling: {
                    "Description": "ARNs of any target groups to attach to the autoscaling configuration",
                    "Type": "String",
                }
            }
        )

        self.templates_dict[Labels.cluster_label]['Resources']['WebserverStack']['Properties'][
            'Parameters'].update(
            {Labels.target_group_arns_for_autoscaling: {"Ref": Labels.target_group_arns_for_autoscaling}}
        )
        self.templates_dict[webserver_label]['Resources']['AutoScalingGroup']['Properties'].update(
            {"TargetGroupARNs": [{"Ref": Labels.target_group_arns_for_autoscaling}]}
        )
        self.templates_dict[Labels.cluster_label]['Parameters'].update(
            {
                Labels.target_group_arns_for_autoscaling:
                    {"Description": "Load balancer name to attach to the autoscaling group", "Type": "String"}
            }
        )

    def update_instance_types(self):
        if self.STAGE_NAMES_AND_CONFIGS:
            # First check that the stage matches, then check if a custom instance type is defined for that stage
            if self.stage_name in self.STAGE_NAMES_AND_CONFIGS:
                if "worker_instance_type" in self.STAGE_NAMES_AND_CONFIGS[self.stage_name]:
                    instance_type = self.STAGE_NAMES_AND_CONFIGS[self.stage_name]["worker_instance_type"]
                    logger.info("Updating templates to use {} as worker instance type from class attribute".format(
                        instance_type))
                    self.templates_dict[Labels.master_label]["Parameters"]["WorkerInstanceType"]["Default"] = instance_type
                else:
                    logger.info("No worker_instance_type detected")
                if "rds_instance_type" in self.STAGE_NAMES_AND_CONFIGS[self.stage_name]:
                    rds_instance_type = self.STAGE_NAMES_AND_CONFIGS[self.stage_name]["rds_instance_type"]
                    logger.info("Updating templates to use {} as rds instance type from class attribute".format(
                        rds_instance_type))
                    self.templates_dict[Labels.cluster_label]["Resources"]["DBInstance"]["DBInstanceClass"] = rds_instance_type
                else:
                    logger.info("No rds_instance_type detected")
                if "max_spot_price" in self.STAGE_NAMES_AND_CONFIGS[self.stage_name]:
                    max_spot_price = self.STAGE_NAMES_AND_CONFIGS[self.stage_name]["max_spot_price"]
                    logger.info("Updating templates to use spot price {}".format(max_spot_price))
                    self.templates_dict[Labels.workerset_label]["Resources"]["LaunchConfiguration"]["Properties"][
                        "SpotPrice"] = max_spot_price
                else:
                    logger.info('No max_spot_price not detected')

        return

    @staticmethod
    def to_pascal_case(filename):
        split_name = filename.split('-')
        return ''.join(map(str.title, split_name))

    def _load_templates(self):
        for template_name in self.template_list:
            with open(os.path.join(self.templates_path,
                                   "turbine-{}.template".format(template_name))) as infile:
                self.templates_dict[template_name] = load_yaml(infile)

    def _add_outputs_for_dashboards(self):
        """ returns the parameters needed for the dashboard to be added"""
        # return a dict of the output keys used
        self.templates_dict[Labels.cluster_label]['Outputs'].update(
            {'SQSTaskQueueName': {'Value': {'Fn::GetAtt': ['TaskQueue', 'QueueName']}}}
        )
        self.templates_dict[Labels.workerset_label]['Outputs'].update(
            {'TurbineStackName': {'Value': {'Ref': 'AWS::StackName'}}}
        )
        # Add outputs to individual stacks
        self.templates_dict[Labels.scheduler_label]['Outputs'].update(
            {'EC2AutoScalingGroupName': {'Value': {'Ref': 'AutoScalingGroup'}}}
        )
        self.templates_dict[Labels.webserver_label]['Outputs'].update(
            {'EC2AutoScalingGroupName': {'Value': {'Ref': 'AutoScalingGroup'}}}
        )
        self.templates_dict[Labels.workerset_label]['Outputs'].update(
            {'EC2AutoScalingGroupName': {'Value': {'Ref': 'AutoScalingGroup'}}}
        )
        # pass them through to cluster stack so it's available at top level
        self.templates_dict[Labels.cluster_label]['Outputs'].update(
            {'TurbineStackName': {'Value': {'Fn::GetAtt': ['WorkerSetStack', 'Outputs.TurbineStackName']}}}
        )
        self.templates_dict[Labels.cluster_label]['Outputs'].update(
            {'EC2AutoScalingGroupName': {
                'Value': {'Fn::GetAtt': ['SchedulerStack', 'Outputs.EC2AutoScalingGroupName']}}}
        )
        self.templates_dict[Labels.cluster_label]['Outputs'].update(
            {'EC2AutoScalingGroupNameWebserver': {
                'Value': {'Fn::GetAtt': ['WebserverStack', 'Outputs.EC2AutoScalingGroupName']}}}
        )
        self.templates_dict[Labels.cluster_label]['Outputs'].update(
            {'EC2AutoScalingGroupNameWorker': {
                'Value': {'Fn::GetAtt': ['WorkerSetStack', 'Outputs.EC2AutoScalingGroupName']}}}
        )

        return {
            'SQSTaskQueueName': {"Fn::GetAtt": ["TurbineCluster", "Outputs.SQSTaskQueueName"]},
            'TurbineStackName': {"Fn::GetAtt": ["TurbineCluster", "Outputs.TurbineStackName"]},
            'EC2AutoScalingGroupName': {"Fn::GetAtt": ["TurbineCluster", "Outputs.EC2AutoScalingGroupName"]},
            'EC2AutoScalingGroupNameWebserver': {
                "Fn::GetAtt": ["TurbineCluster", "Outputs.EC2AutoScalingGroupNameWebserver"]},
            'EC2AutoScalingGroupNameWorker': {
                "Fn::GetAtt": ["TurbineCluster", "Outputs.EC2AutoScalingGroupNameWorker"]},
        }

    def add_instance_and_autoscaling_group_metrics(self):

        """"""
        metrics_userdata = [
            # add to this to userdata
            "aws configure set default.region ${AWS::Region}\n",
            "cat <<EOF > /usr/local/bin/metricscript.sh\n",
            "# !/bin/bash\n",
            "\n",
            "# Collect region and instanceid from metadata\n",
            "AWSREGION=\$(curl -ss http://169.254.169.254/latest/dynamic/instance-identity/document | jq -r .region)\n",
            "AWSINSTANCEID=\$(curl -ss http://169.254.169.254/latest/meta-data/instance-id)\n",
            "AWSAUTOSCALINGGROUP=\$(aws autoscaling describe-auto-scaling-instances --instance-ids=\$AWSINSTANCEID --region  \$AWSREGION | jq .AutoScalingInstances[0].AutoScalingGroupName)\n",
            "\n",
            "\n",
            "function getMetric {\n",
            "  # Always return bytes\n",
            "  if [ \"\$1\" == \"DiskTotal\" ]; then\n",
            "    total=\$(df / | awk '/dev/ {print \$2}')\n",
            "    echo \$(( \$total*1000 ))\n",
            "  elif [ \"\$1\" == \"DiskUsed\" ]; then\n",
            "    used=\$(df / | awk '/dev/ {print \$3}')\n",
            "    echo \$(( \$used*1000 ))\n",
            "  elif [ \"\$1\" == \"DiskFree\" ]; then\n",
            "    free=\$(df / | awk '/dev/ {print \$4}')\n",
            "    echo \$(( \$free*1000 ))\n",
            "  elif [ \"\$1\" == \"MemTotal\" ]; then\n",
            "    free -b | awk '/Mem:/ {print \$2}'\n",
            "  elif [ \"\$1\" == \"MemUsed\" ]; then\n",
            "    used=\$(free -b | awk '/Mem:/ {print \$3}')\n",
            "    shared=\$(free -b | awk '/Mem:/ {print \$5}')\n",
            "    buff=\$(free -b | awk '/Mem:/ {print \$6}')\n",
            "    echo \$((\$used + \$shared + \$buff))\n",
            "  elif [ \"\$1\" == \"MemFree\" ]; then\n",
            "    free -b | awk '/Mem:/ {print \$4}'\n",
            "  elif [ \"\$1\" == \"CPUUsage\" ]; then\n",
            "    grep 'cpu ' /proc/stat | awk '{usage=(\$2+\$4)*100/(\$2+\$4+\$5)} END {print usage}'\n ",
            "  fi\n",
            "}\n",
            "\n",
            "# Disk usage metrics\n",
            # "data=\$( getMetric DiskTotal )\n",
            # "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name DiskTotal --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            # "data=\$( getMetric DiskUsed )\n",
            # "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name DiskUsed --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            "data=\$( getMetric DiskFree )\n",
            "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name DiskFree --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            "# Memory usage metrics\n",
            # "data=\$( getMetric MemTotal )\n",
            # "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name MemTotal --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            # "data=\$( getMetric MemUsed )\n",
            # "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name MemUsed --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            "data=\$( getMetric MemFree )\n",
            "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name MemFree --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            "# CPU usage metrics\n",
            "data=\$( getMetric CPUUsage )\n",
            "aws cloudwatch put-metric-data --value \$data --namespace Deductive/AutoScalingGroup/Instance --unit Bytes --metric-name CPUUsage --dimensions AutoScalingGroup=\$AWSAUTOSCALINGGROUP,Instance=\$AWSINSTANCEID --region  \$AWSREGION\n",
            "EOF\n",
            "\n",
            "chmod +x /usr/local/bin/metricscript.sh\n",
            "\n",
            "cat <<EOF > /etc/cron.d/autoscalinggroupmetrics\n",
            "*/5 * * * * root /usr/local/bin/metricscript.sh\n",
            "EOF\n",
            "\n",
            "# Test metrics script\n",
            "/usr/local/bin/metricscript.sh\n",
            "\n",
            """
          /opt/aws/bin/cfn-signal -e $?
            --region ${AWS::Region} \
            --stack ${AWS::StackName} \
            --resource LaunchConfiguration"""
        ]

        def join_to_userdata(cluster):
            """ add userdata to turbine cluster"""
            existing_userdata = cluster['Resources']['LaunchConfiguration']['Properties']['UserData']['Fn::Base64'][
                'Fn::Sub']
            cluster['Resources']['LaunchConfiguration']['Properties']['UserData']['Fn::Base64']['Fn::Sub'] = "".join(
                [existing_userdata, *metrics_userdata])

        join_to_userdata(self.templates_dict['workerset'])
        join_to_userdata(self.templates_dict['webserver'])
        join_to_userdata(self.templates_dict['scheduler'])

    def save_templates(self):
        for template_name in self.templates_dict.keys():
            with open(os.path.join(self.updated_templates_path,
                                   "turbine-{}.template".format(template_name)), 'w') as outfile:
                outfile.write(dump_yaml(self.templates_dict[template_name]))

    def add_policies(self, policies_base_path=""):

        for template_name in self.templates_dict.keys():
            policies_list = glob.glob(
                os.path.join(policies_base_path or self.policies_base_path, template_name, '*.json'))

            if policies_list:
                for policy_path in policies_list:
                    with open(policy_path) as policy:
                        policy_loaded = json.load(policy)
                        for i in range(len(policy_loaded["Statement"])):
                            policy_loaded["Statement"][i]["Resource"] = [{'Fn::Sub': resource} for resource in
                                                                         policy_loaded["Statement"][i]["Resource"]]
                        policy_name = policy_path.rsplit('/')[-1].split('.')[0]
                        new_policy = {'PolicyName': {
                            'Fn::Sub': '{policy_name}-{stage_name}-{nesting}'.format(policy_name=policy_name,
                                                                                     stage_name=self.stage_name,
                                                                                     nesting=template_name)},
                            'PolicyDocument': policy_loaded}

                        self.templates_dict[template_name]['Resources']['IamRole']['Properties']['Policies'].append(
                            new_policy)

            managed_policies = glob.glob(
                os.path.join(policies_base_path or self.policies_base_path, template_name, 'managed_policies.txt'))
            if managed_policies:
                with open(managed_policies[0]) as m_policies:
                    arn_list = m_policies.read().splitlines()
                    arn_list = [{'Fn::Sub': x} for x in arn_list]
                    self.templates_dict[template_name]['Resources']['IamRole']['Properties'][
                        'ManagedPolicyArns'] += arn_list

    def add_template(self, additional_template_path, parameters_and_vals={}):

        with open(additional_template_path) as template_file:
            # Load yaml used for now but this can be changed if need be
            additional_template = load_yaml(template_file.read())

        if 'Parameters' in additional_template.keys():
            template_params = {key: value for key, value in additional_template['Parameters'].items() if
                               key not in parameters_and_vals.keys()}
            add_keys_list = additional_template['Parameters'].keys()
            resource_params = {param: {'Ref': param} for param in additional_template['Parameters'].keys() if
                               param not in parameters_and_vals.keys()}

            resource_params = {**resource_params, **parameters_and_vals}

        else:
            if parameters_and_vals:
                raise ValueError('There are no input parameters on the template can not pass in extra_param_values')
            template_params = {}
            add_keys_list = []
            resource_params = None

        existing_keys_lists = self.templates_dict[Labels.master_label]['Parameters'].keys()

        overlapped_keys = [new_key for new_key in existing_keys_lists if new_key in add_keys_list]
        if len(overlapped_keys):
            raise KeyError(
                'There is an overlap in parameters between the additional template and the master template. {}'.format(
                    str(overlapped_keys)))

        # Use filename converted to PascalCase to set the name of the stack resource
        template_file_name = additional_template_path.rsplit('.', 1)[0].rsplit('/', 1)[-1]
        sub_stack_name = self.to_pascal_case(template_file_name)

        template_path_s3 = 'templates/additional_templates/' + additional_template_path.rsplit('/')[-1]
        template_url = {'Fn::Join': ['', [{'Fn::Sub': 'https://${QSS3BucketName}.s3.amazonaws.com/'},
                                          {'Ref': 'QSS3KeyPrefix'}, template_path_s3]]}

        self.templates_dict[Labels.master_label]['Parameters'] = {**self.templates_dict[Labels.master_label]['Parameters'],
                                                       **template_params}
        if resource_params:
            resource_add = {sub_stack_name: {'Type': 'AWS::CloudFormation::Stack',
                                             'Properties': {'TemplateURL': template_url,
                                                            'Parameters': resource_params}}}
        else:
            resource_add = {sub_stack_name: {'Type': 'AWS::CloudFormation::Stack',
                                             'Properties': {'TemplateURL': template_url}}}

        self.templates_dict[Labels.master_label]['Resources'].update(resource_add)

    def update_templates(self, additional_template_path=None):
        self.add_policies()
        if additional_template_path:
            self.add_template(additional_template_path,
                              parameters_and_vals={"VpcId": {"Fn::GetAtt": ["VPCStack", "Outputs.VPCID"]}})
        self.save_templates()

    def generate_dashboard_template(self, stage_name, source_path, template_path):
        """
        adds a basic generic dashboard with tracking on the webserver, scheduler and worker nodes.
        To expand this method, subclass as needed
        :param stage_name: name of stage being deployed to, user to identify unique dashboards
        :param source_path: path to dashboard templates
        :param template_path: path to dashboard templates
        :return: path to dashboard template file as str and the parameters needed as a dict
        """
        outputs = self._add_outputs_for_dashboards()
        self.add_instance_and_autoscaling_group_metrics()
        dashboard_policies_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "dashboards", "policies")
        self.add_policies(dashboard_policies_path)
        dashboard = DativaDashboardTemplate(
            self.project_name,
            stage_name=stage_name,
            source_path=source_path,
            template_path=template_path
        )

        dashboard_template = dashboard.generate_template(**outputs)
        return dashboard_template, outputs

    def add_cloudtrail(self):
        """
        Deploy CloudTrail
        """
        cloudtrail_bucket_dict = {
            "Type": "AWS::S3::Bucket",
            "Properties": {
                "BucketName": "{project_name}-{stage_name}-cloudtrail-logs".format(
                    project_name=self.project_name.lower(),
                    stage_name=self.stage_name.lower()),
            },
            "DeletionPolicy": "Retain"
        }
        self.templates_dict[Labels.master_label]["Resources"]["CloudTrailLogsBucket"] = cloudtrail_bucket_dict

        policy_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   "cloudtrail/policies/cloudtrail_logs_bucket_policy.json")
        with open(policy_path) as infile:
            cloudtrail_policy = json.loads(infile.read())

        self.templates_dict[Labels.master_label]["Resources"]["CloudTrailLogsBucketPolicy"] = {
            "Type": "AWS::S3::BucketPolicy",
            "Properties": {
                "Bucket": {"Ref": "CloudTrailLogsBucket"},
                "PolicyDocument": cloudtrail_policy
            }
        }

        self.templates_dict[Labels.master_label]["Resources"]["CloudTrail"] = {
            "Type": "AWS::CloudTrail::Trail",
            "Properties": {
                "IsLogging": True,
                "S3BucketName": {"Ref": "CloudTrailLogsBucket"}
            },
            "DependsOn": ["CloudTrailLogsBucketPolicy"]
        }


class LoadBalancerTemplate:

    def __init__(self, stage_name, region, domain, random_string, project_name, prod_like_stacks, allowed_stages):
        self._project_name = project_name
        self._project_name_alphanum = project_name.replace("-", "").replace("_", "")
        self._basepath = "./unpackaged-templates/"
        self._stage_name = stage_name
        self._region = region
        self._prod_like_stacks = prod_like_stacks
        self._prod_like_logical = self._stage_name in self._prod_like_stacks
        self._mapping_and_transformation = {
            # e.g. DEV in us-west-2 would become 'dev-us-west-2'
            "LowerStage": lambda x: "-".join([x, self._region]).lower().replace("_", "-"),
            # e.g. DEV in us-west-2 would become 'dev_us_west_2'
            "LowerUnderStage": lambda x: "_".join([x, self._region]).lower().replace("-", "_"),
            # e.g. DEV in us-west-2 would become DevUsWest2
            "CamelNoSepStage": lambda x: "".join([x, self._region]).title().replace("-", "").replace("_", ""),
        }
        self.current_mapping_vals = {
            mapping: transformation(self._stage_name)
            for mapping, transformation in self._mapping_and_transformation.items()
        }
        self._file_ext = ".template"
        self.stage_name_subdomain_mapping = {stage: self._project_name + "-" + stage.lower() for stage in
                                             allowed_stages}
        self.stage_name_subdomain_mapping["PROD"] = self._project_name
        self.domain = domain
        self.alias = "{}.{}".format(self.stage_name_subdomain_mapping[self._stage_name], self.domain)
        self.random_string = random_string

    @staticmethod
    def _get_custom_error_responses():
        return [
            cloudfront.CustomErrorResponse(
                ErrorCachingMinTTL=300,
                ErrorCode=403,
                ResponseCode=200,
                ResponsePagePath="/index.html"
            ),
            cloudfront.CustomErrorResponse(
                ErrorCachingMinTTL=300,
                ErrorCode=404,
                ResponseCode=200,
                ResponsePagePath="/index.html"
            ),
        ]

    def _get_bucket_encryption_config(self):
        encryption_config = s3.BucketEncryption(
            ServerSideEncryptionConfiguration=[s3.ServerSideEncryptionRule(
                ServerSideEncryptionByDefault=s3.ServerSideEncryptionByDefault(
                    SSEAlgorithm='AES'
                )
            )]
        )
        return encryption_config

    def loadbalancer_and_routing(self):
        t = Template("AWS CloudFormation template:"
                     " Contains the CloudFront Distributions and appropriate routing to make it work.")
        t.add_parameter(Parameter(
            "SSLCertArn",
            Type="String"))
        t.add_parameter(Parameter(
            Labels.subnet_ids,
            Type="String",
            Description="Subnet IDs to use for the load balancer"
        ))
        t.add_parameter(Parameter(
            Labels.vpc_id_for_sgs,
            Type="String",
            Description="VPC ID to be used for the load balancer and target group"
        ))
        t.add_parameter(Parameter(
            Labels.vpc_s3_endpoint_id,
            Type="String",
            Description="VPC S3 endpoint ID for use in the loadbalancer to log to"
        ))

        # define application load balancer here
        load_balancer = "LoadBalancer"
        webserver_target_group = "WebserverTargetGroup"
        t.add_resource(elasticloadbalancingv2.TargetGroup(
            webserver_target_group,
            HealthCheckProtocol="HTTP",
            Protocol="HTTP",
            Matcher=elasticloadbalancingv2.Matcher(HttpCode="302"),
            Port=80,
            TargetType="instance",
            Name="{}Web{}{}".format(
                self._project_name_alphanum,
                self.current_mapping_vals["CamelNoSepStage"],
                self.random_string
            ),
            VpcId=Ref(Labels.vpc_id_for_sgs),
        ))

        sg = ec2.SecurityGroup(
            "SgOpenAll",
            GroupDescription="A security group to hold IP addresses which allow access to CloudFront",
            GroupName="{}SgOpenAll{}".format(self._project_name_alphanum, self.current_mapping_vals["CamelNoSepStage"]),
            SecurityGroupIngress=[
                ec2.SecurityGroupRule(
                    IpProtocol="tcp", ToPort=80, FromPort=80,
                    CidrIp="0.0.0.0/0", Description="OpenAllHTTP"
                ),
                ec2.SecurityGroupRule(
                    IpProtocol="tcp", ToPort=443, FromPort=443,
                    CidrIp="0.0.0.0/0", Description="OpenAllHTTPS"
                ),
            ],
            SecurityGroupEgress=[
                ec2.SecurityGroupRule(
                    IpProtocol="tcp", ToPort=80, FromPort=80,
                    CidrIp="0.0.0.0/0", Description="OpenAllHTTP"
                ),
                ec2.SecurityGroupRule(
                    IpProtocol="tcp", ToPort=443, FromPort=443,
                    CidrIp="0.0.0.0/0", Description="OpenAllHTTPS"
                ),
            ],
            VpcId=Ref(Labels.vpc_id_for_sgs),
        )
        t.add_resource(sg)

        if self._prod_like_logical:
            bucket_name = Join("-", [self._project_name, "load-balancer-logging-bucket", AccountId, self._stage_name.lower()])
            bucket_prefix = "application-load-balancer-logs/data-ingest-reporting/{}".format(self._stage_name.lower())
            load_balancer_attributes = [
                elasticloadbalancingv2.LoadBalancerAttributes(
                    Key="access_logs.s3.enabled", Value="true"),
                elasticloadbalancingv2.LoadBalancerAttributes(
                    Key="access_logs.s3.bucket", Value=bucket_name),
                elasticloadbalancingv2.LoadBalancerAttributes(
                    Key="access_logs.s3.prefix", Value=bucket_prefix),
            ]

            loadbalancer_bucket_logical_id = "LoadbalancerLogsBucket"
            load_balancer_bucket = s3.Bucket(
                loadbalancer_bucket_logical_id,
                BucketName=bucket_name,
                DeletionPolicy="Retain",
                AccessControl="LogDeliveryWrite",
                # BucketEncryption=self._get_bucket_encryption_config(),
            )

            t.add_resource(load_balancer_bucket)
            policy_logical_id = loadbalancer_bucket_logical_id + "BucketPolicy"
            t.add_resource(s3.BucketPolicy(
                policy_logical_id,
                PolicyDocument=PolicyDocument(
                    Version="2012-10-17",
                    Id="AccessLogsPolicy",
                    Statement=[
                        Statement(
                            Sid="AWSConsoleStmt-1592839844977",
                            Effect="Allow",
                            Principal=Principal(
                                "AWS", "arn:aws:iam::127311923021:root"
                            ),
                            Action=[Action("s3", "PutObject")],
                            Resource=[Join("/", [GetAtt(loadbalancer_bucket_logical_id, "Arn"), "*"])]
                        ),
                        Statement(
                            Sid="AWSLogDeliveryWrite",
                            Effect="Allow",
                            Principal=Principal(
                                "Service", "delivery.logs.amazonaws.com"
                            ),
                            Action=[Action("s3", "PutObject")],
                            Resource=[Join("/", [GetAtt(loadbalancer_bucket_logical_id, "Arn"), "*"])],
                            Condition=Condition(StringEquals("s3:x-amz-acl", "bucket-owner-full-control")),
                        ),
                        Statement(
                            Sid="AWSLogDeliveryAclCheck",
                            Effect="Allow",
                            Principal=Principal("Service", "delivery.logs.amazonaws.com"),
                            Action=[Action("s3", "GetBucketAcl")],
                            Resource=[GetAtt(loadbalancer_bucket_logical_id, "Arn")]
                        )
                    ]
                ),
                Bucket=Ref(loadbalancer_bucket_logical_id),
                DependsOn=[loadbalancer_bucket_logical_id]
            ))
        else:
            load_balancer_bucket = NoValue
            load_balancer_attributes = NoValue
            policy_logical_id = NoValue

        t.add_resource(elasticloadbalancingv2.LoadBalancer(
            load_balancer,
            Scheme="internet-facing",
            LoadBalancerAttributes=load_balancer_attributes,
            SecurityGroups=[Ref(sg)],
            Name="{}Psyclone{}".format(self._project_name_alphanum, self.current_mapping_vals["CamelNoSepStage"]),
            Subnets=Split(",", Ref(Labels.subnet_ids)),
            Type="application",
            DependsOn=[load_balancer_bucket, policy_logical_id] if self._prod_like_logical else []
        ))

        t.add_resource(elasticloadbalancingv2.Listener(
            "HTTPRedirectToWebserver",
            Port="80",
            Protocol="HTTP",
            LoadBalancerArn=Ref(load_balancer),
            DefaultActions=[
                elasticloadbalancingv2.Action(
                    RedirectConfig=elasticloadbalancingv2.RedirectConfig(
                        Port="443",
                        Protocol="HTTPS",
                        StatusCode="HTTP_301"
                    ),
                    Type="redirect",
                )
            ]
        ))

        t.add_resource(elasticloadbalancingv2.Listener(
            "HTTPSToWebserver",
            Certificates=[elasticloadbalancingv2.Certificate(CertificateArn=Ref("SSLCertArn"))],
            Port="443",
            Protocol="HTTPS",
            LoadBalancerArn=Ref(load_balancer),
            DefaultActions=[
                elasticloadbalancingv2.Action(
                    TargetGroupArn=Ref(webserver_target_group),
                    Type="forward",
                )
            ]
        ))

        hosted_zone_name = self.domain + "."
        t.add_resource(
            route53.RecordSetType(
                "CloudFrontDistributionToEC2{}".format(self.current_mapping_vals["CamelNoSepStage"]),
                HostedZoneName=hosted_zone_name,
                Comment="CNAME redirect to aws.amazon.com.",
                Name=self.alias,
                Type="CNAME",
                TTL="300",
                ResourceRecords=[GetAtt(load_balancer, "DNSName")],
            )
        )
        t.add_output(Output(
            Labels.target_group_arns_for_autoscaling,
            Value=Ref(webserver_target_group),
            Description="ARN for target group associated with the webserver"
        ))
        return t

    def get_output_filename(self, stack_name):
        output_path = "{}{}{}".format(self._basepath, stack_name, self._file_ext)
        return output_path

    def write_to_file(self, stack_name, t):
        output_path = self.get_output_filename(stack_name)
        yml_string = t.to_yaml()
        logger.info("Writing to {}".format(output_path))
        with open(output_path, "w") as f:
            f.write(yml_string)
        return output_path

    @staticmethod
    def write_modified_airflow_config(path_to_config, stage_name, project_name, domain):
        cfg = configparser.ConfigParser()
        cfg.read(path_to_config)
        lower_under_stage = stage_name.lower().replace('-', '_')
        lower_under_project_name = project_name.lower().replace('-', '_')

        try:
            alias = "{}.{}".format(stage_name, domain)
        except KeyError:
            alias = ''
        # Update URL used on emails to link to log files etc
        if alias:
            cfg.set('webserver', 'base_url', "http://" + alias)

        email_address = "{}_{}_{}".format(lower_under_stage, lower_under_project_name, 'airflow@psyclone.com')
        # Update email address which delivers updates to give stackname
        cfg.set('webserver', 'smtp_mail_from', email_address)
        # Update URL used on emails to link to log files etc
        cfg.set('webserver', 'base_url', "http://" + alias)

        # Add section for custom config args
        # - intended to avoid conflict with existing or new variables from airflow or turbine
        cfg.add_section('deductive_custom')
        cfg.set("deductive_custom", "stage_name", stage_name)
        cfg.set("deductive_custom", "google_auth_secret_key", "data-ingest/DEV/google-api-secret")
        with open(path_to_config, "w") as file:
            cfg.write(file)
